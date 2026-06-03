"""
Background ML trade-timing analysis for the dashboard (super_admin).

Environment routing (strict):
- Local run (python dashboard/app.py): reads DATABASE_URL → local Postgres/SQLite only.
- Deployed production (PythonAnywhere, etc.): reads DATABASE_URL → production Postgres only.

CLI scripts (--production) are separate; this module never opens an SSH tunnel on local runs.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Literal, Optional
from urllib.parse import urlparse

from research.db_source import describe_active_source

logger = logging.getLogger(__name__)

MlRuntimeMode = Literal["local", "production"]

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "status": "idle",
    "html": "",
    "closed_history_html": "",
    "meta": {},
    "error": None,
    "generated_at": None,
    "started_at": None,
    "refresh_interval_sec": 300,
    "last_duration_sec": None,
}

_worker_lock = threading.Lock()
_refresh_lock = threading.Lock()
_debounce_lock = threading.Lock()
_worker_started = False
_stop_event = threading.Event()
_data_changed_event = threading.Event()
_leader_lock_handle = None  # keeps flock open for process lifetime (Linux/PA)
_debounce_timer: Optional[threading.Timer] = None
_refresh_queued = False
_last_db_fingerprint: Optional[tuple] = None
_last_scheduled_refresh_at: float = 0.0


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ml_runtime_mode() -> MlRuntimeMode:
    """local = dev machine; production = deployed host (PythonAnywhere, etc.)."""
    return "production" if _is_deployed_production() else "local"


def _cache_dir() -> Path:
    override = (os.environ.get("ML_CACHE_DIR") or "").strip()
    base = Path(override) if override else Path(_project_root()) / "dashboard" / "instance" / "ml_cache"
    return base / _ml_runtime_mode()


def _cache_html_path() -> Path:
    return _cache_dir() / "report.html"


def _cache_closed_history_path() -> Path:
    return _cache_dir() / "closed_history.html"


def _cache_meta_path() -> Path:
    return _cache_dir() / "meta.json"


def _leader_lock_path() -> Path:
    """Fixed path so all uWSGI workers agree on the same lock file."""
    override = (os.environ.get("ML_CACHE_DIR") or "").strip()
    base = Path(override) if override else Path(_project_root()) / "dashboard" / "instance" / "ml_cache"
    return base / ".ml_worker_leader.lock"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, default=str))


def _persist_cache(
    html: str,
    meta: Dict[str, Any],
    *,
    closed_history_html: str = "",
) -> None:
    try:
        _atomic_write_text(_cache_html_path(), html)
        if closed_history_html:
            _atomic_write_text(_cache_closed_history_path(), closed_history_html)
        _atomic_write_json(
            _cache_meta_path(),
            {
                "status": _state.get("status"),
                "meta": meta,
                "error": _state.get("error"),
                "generated_at": _state.get("generated_at"),
                "started_at": _state.get("started_at"),
                "refresh_interval_sec": _state.get("refresh_interval_sec"),
                "last_duration_sec": _state.get("last_duration_sec"),
                "runtime_mode": _ml_runtime_mode(),
            },
        )
    except OSError as e:
        logger.warning("[ML] Could not write disk cache: %s", e)


def _load_disk_cache() -> Optional[Dict[str, Any]]:
    meta_path = _cache_meta_path()
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[ML] Could not read disk cache meta: %s", e)
        return None


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_project_root(), ".env"))
    except ImportError:
        pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _is_local_db_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("", "localhost", "127.0.0.1")


def _is_deployed_production() -> bool:
    """
    True only on the production host — not when developing on a PC with .env tunnel vars.
    """
    _load_env()
    if _env_bool("ML_DEPLOYED_PRODUCTION"):
        return True
    if (os.environ.get("PYTHONANYWHERE_SITE") or "").strip():
        return True
    if (os.environ.get("DEPLOYMENT") or "").strip().lower() in (
        "production",
        "prod",
        "pythonanywhere",
    ):
        return True
    return False


def _prepare_database_for_refresh() -> None:
    """
    Validate DATABASE_URL for this runtime mode.
    Does not reset the connection pool — ML reads use get_direct_connection()
    and resetting the pool under uWSGI disrupts concurrent /api/update_data requests.
    """
    from dashboard import database as db

    _load_env()
    url = (os.environ.get("DATABASE_URL") or db.DATABASE_URL or "").strip()
    mode = _ml_runtime_mode()

    if mode == "production":
        if not url or url.startswith("sqlite"):
            url = (os.environ.get("PRODUCTION_DATABASE_URL") or "").strip()
            if not url:
                from research.db_source import resolve_production_url

                url = resolve_production_url()
        if _is_local_db_url(url):
            raise RuntimeError(
                "Production deploy must set DATABASE_URL to PythonAnywhere Postgres "
                "(not localhost). Check Web app environment variables."
            )
        if url and url != db.DATABASE_URL:
            db.set_database_url(url)


@contextmanager
def _ml_data_session() -> Iterator[str]:
    mode = _ml_runtime_mode()
    _prepare_database_for_refresh()
    yield describe_active_source(mode)


def _use_watch_mode() -> bool:
    """Default: watch clients_data and refresh when it changes (debounced)."""
    return os.environ.get("ML_REFRESH_MODE", "watch").strip().lower() != "interval"


def _interval_sec() -> int:
    """Legacy fixed-interval mode only (ML_REFRESH_MODE=interval)."""
    explicit = (os.environ.get("ML_REFRESH_INTERVAL_SEC") or "").strip()
    if explicit:
        try:
            return max(60, int(explicit))
        except ValueError:
            pass
    return 120 if _ml_runtime_mode() == "production" else 300


def _watch_poll_sec() -> float:
    """Lightweight DB fingerprint poll (not a full ML rebuild)."""
    explicit = (os.environ.get("ML_WATCH_POLL_SEC") or "").strip()
    if explicit:
        try:
            return max(1.0, float(explicit))
        except ValueError:
            pass
    return 3.0 if _ml_runtime_mode() == "production" else 5.0


def _debounce_sec() -> float:
    """Wait after last data change before starting heavy sklearn refresh."""
    explicit = (os.environ.get("ML_REFRESH_DEBOUNCE_SEC") or "").strip()
    if explicit:
        try:
            return max(5.0, float(explicit))
        except ValueError:
            pass
    return 20.0 if _ml_runtime_mode() == "production" else 30.0


def _fallback_interval_sec() -> int:
    """Safety-net full refresh if watch misses a change (0 = disabled)."""
    explicit = (os.environ.get("ML_FALLBACK_INTERVAL_SEC") or "").strip()
    if explicit:
        try:
            return max(0, int(explicit))
        except ValueError:
            pass
    return 1800 if _ml_runtime_mode() == "production" else 0


def _read_db_fingerprint() -> tuple:
    fresh = _clients_data_freshness()
    max_u = fresh.get("db_max_last_updated")
    n = fresh.get("db_client_count", 0)
    return (str(max_u) if max_u is not None else "", int(n or 0))


def notify_clients_data_changed(source: str = "save") -> None:
    """Wake the watch worker immediately (e.g. after companion push / save)."""
    _data_changed_event.set()
    logger.debug("[ML] Data change signal (%s)", source)


def _schedule_debounced_refresh(reason: str) -> None:
    """Coalesce bursts of pushes into one heavy refresh (runs on a timer thread)."""
    global _debounce_timer

    def _fire() -> None:
        global _last_scheduled_refresh_at
        _last_scheduled_refresh_at = time.time()
        fp_before = _read_db_fingerprint()
        refresh_now(reason=reason)
        fp_after = _read_db_fingerprint()
        global _last_db_fingerprint
        _last_db_fingerprint = fp_after
        if fp_after != fp_before:
            logger.info("[ML] DB changed during refresh — scheduling follow-up")
            _schedule_debounced_refresh("coalesce")

    with _debounce_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(_debounce_sec(), _fire)
        _debounce_timer.daemon = True
        _debounce_timer.start()
    logger.info("[ML] Refresh scheduled in %.0fs (%s)", _debounce_sec(), reason)


def _on_db_fingerprint_changed(reason: str) -> None:
    global _last_db_fingerprint
    fp = _read_db_fingerprint()
    if _last_db_fingerprint is not None and fp == _last_db_fingerprint:
        return
    logger.info("[ML] clients_data changed (%s) %s → %s", reason, _last_db_fingerprint, fp)
    _schedule_debounced_refresh(reason)


def _heal_disk_meta() -> None:
    """After uWSGI SIGTERM, meta.json can say 'running' while report.html is valid."""
    if not _cache_meta_path().is_file() or not _cache_html_path().is_file():
        return
    disk = _load_disk_cache()
    if not disk or disk.get("status") != "running":
        return
    disk["status"] = "ready"
    disk["error"] = None
    try:
        _atomic_write_json(_cache_meta_path(), disk)
        logger.info("[ML] Healed disk cache meta (running -> ready, report on disk)")
    except OSError as e:
        logger.warning("[ML] Could not heal disk meta: %s", e)


def _warm_memory_from_disk() -> None:
    """So any uWSGI worker can serve the last good report immediately."""
    html = ""
    path = _cache_html_path()
    if path.is_file():
        try:
            html = path.read_text(encoding="utf-8")
        except OSError:
            return
    if not html:
        return
    closed_hist = ""
    ch_path = _cache_closed_history_path()
    if ch_path.is_file():
        try:
            closed_hist = ch_path.read_text(encoding="utf-8")
        except OSError:
            closed_hist = ""
    disk = _load_disk_cache() or {}
    with _lock:
        if _state.get("html"):
            return
        _state["html"] = html
        _state["closed_history_html"] = closed_hist
        _state["meta"] = dict(disk.get("meta") or {})
        _state["generated_at"] = disk.get("generated_at")
        _state["error"] = disk.get("error")
        st = disk.get("status") or "ready"
        _state["status"] = "ready" if st == "running" and html else st


def _recover_stale_running(max_minutes: int = 5) -> None:
    """In-memory refresh stuck after reload (production reloads every few minutes)."""
    with _lock:
        if _state.get("status") != "running":
            return
        started = _state.get("started_at") or ""
    if not started:
        return
    try:
        t0 = datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return
    if (datetime.now() - t0).total_seconds() <= max_minutes * 60:
        return
    with _lock:
        if _cache_html_path().is_file():
            _state["status"] = "ready"
            _state["error"] = "Previous refresh was interrupted; showing last cached report."
        else:
            _state["status"] = "error"
            _state["error"] = "Refresh interrupted (app reload). Click Refresh now."


def _startup_delay_sec() -> int:
    try:
        return max(0, int(os.environ.get("ML_REFRESH_STARTUP_DELAY_SEC", "45")))
    except ValueError:
        return 45


def _use_subprocess_refresh() -> bool:
    """Isolate heavy sklearn work from uWSGI workers (avoids 502 / harakiri)."""
    raw = os.environ.get("ML_USE_SUBPROCESS", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return _ml_runtime_mode() == "production"


def _refresh_timeout_sec() -> int:
    try:
        return max(120, int(os.environ.get("ML_REFRESH_TIMEOUT_SEC", "600")))
    except ValueError:
        return 600


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "item") and callable(getattr(obj, "item", None)):
        try:
            return obj.item()
        except (TypeError, ValueError):
            pass
    return obj


def get_state() -> Dict[str, Any]:
    _recover_stale_running()
    mode = _ml_runtime_mode()
    with _lock:
        mem_status = _state["status"]
        out = {
            "status": mem_status,
            "meta": dict(_state.get("meta") or {}),
            "error": _state.get("error"),
            "generated_at": _state.get("generated_at"),
            "started_at": _state.get("started_at"),
            "refresh_interval_sec": _state.get("refresh_interval_sec"),
            "refresh_mode": _state.get("refresh_mode", "watch" if _use_watch_mode() else "interval"),
            "watch_poll_sec": _state.get("watch_poll_sec", _watch_poll_sec()),
            "debounce_sec": _state.get("debounce_sec", _debounce_sec()),
            "last_duration_sec": _state.get("last_duration_sec"),
            "has_html": bool(_state.get("html")),
            "runtime_mode": mode,
            "deployed": mode == "production",
            "uses_production": mode == "production",
            "cache_dir": str(_cache_dir()),
            "refresh_in_progress": mem_status == "running",
        }

    disk = _load_disk_cache()
    if disk:
        if not out["has_html"] and _cache_html_path().is_file():
            out["has_html"] = True
        if out["status"] == "idle" and disk.get("status"):
            out["status"] = "ready" if disk.get("status") == "running" else disk["status"]
        if not out["generated_at"] and disk.get("generated_at"):
            out["generated_at"] = disk["generated_at"]
        if not out["meta"] and disk.get("meta"):
            out["meta"] = dict(disk["meta"])

    # UI can show last report while a new refresh runs
    if out["has_html"] and out["refresh_in_progress"]:
        out["status"] = "ready"
    if out["status"] == "ready" and out["has_html"]:
        with _lock:
            out["error"] = _state.get("error")
    elif not out["error"] and disk and disk.get("error"):
        out["error"] = disk.get("error")
    return _sanitize_for_json(out)


def get_cached_html() -> str:
    with _lock:
        if _state.get("html"):
            return _state["html"]
    path = _cache_html_path()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[ML] Could not read disk cache html: %s", e)
    return ""


def get_cached_closed_history_html() -> str:
    with _lock:
        if _state.get("closed_history_html"):
            return _state["closed_history_html"]
    path = _cache_closed_history_path()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[ML] Could not read closed history cache: %s", e)
    return ""


def _clients_data_freshness() -> Dict[str, Any]:
    from dashboard.database import get_direct_connection

    with get_direct_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(last_updated) AS max_updated, COUNT(*) AS n_clients
            FROM clients_data
            """
        ).fetchone()
    if not row:
        return {}
    return {
        "db_max_last_updated": row["max_updated"],
        "db_client_count": row["n_clients"],
    }


def _set_running() -> None:
    with _lock:
        _state["status"] = "running"
        _state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _state["error"] = None


def _set_result(
    html: str,
    meta: Dict[str, Any],
    duration_sec: float,
    *,
    closed_history_html: str = "",
) -> None:
    with _lock:
        _state["status"] = "ready"
        _state["html"] = html
        _state["closed_history_html"] = closed_history_html
        _state["meta"] = meta
        _state["error"] = None
        _state["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _state["last_duration_sec"] = round(duration_sec, 1)
        if _use_watch_mode():
            _state["refresh_mode"] = "watch"
            _state["watch_poll_sec"] = _watch_poll_sec()
            _state["debounce_sec"] = _debounce_sec()
            _state["refresh_interval_sec"] = _debounce_sec()
        else:
            _state["refresh_mode"] = "interval"
            _state["refresh_interval_sec"] = _interval_sec()
    _persist_cache(html, meta, closed_history_html=closed_history_html)


def _set_error(msg: str, duration_sec: Optional[float] = None) -> None:
    with _lock:
        _state["error"] = msg
        if duration_sec is not None:
            _state["last_duration_sec"] = round(duration_sec, 1)
        _state["status"] = "ready" if _state.get("html") else "error"
        html = _state.get("html") or ""
        meta = dict(_state.get("meta") or {})
    if html:
        _persist_cache(html, meta)


def _execute_refresh(*, reason: str, source_line: str, t0: float) -> None:
    import pandas as pd

    from research.trade_dataset import load_active_positions_df, load_all_round_trips
    from research.ml_analysis import run_full_analysis, render_ml_html_report
    from research.ml_html_report import render_closed_history_full_html

    df = load_all_round_trips(attach_positions=True)
    active = load_active_positions_df()
    analysis = run_full_analysis(df, active_df=active)

    closed_df = analysis.get("closed_trades")
    if closed_df is None:
        closed_df = analysis.get("df")
    closed_history_html = render_closed_history_full_html(
        closed_df if isinstance(closed_df, pd.DataFrame) else pd.DataFrame(),
    )

    html_out = render_ml_html_report(
        analysis,
        data_source_line=source_line,
        title="ML Trade Timing — Live Portfolio",
    )

    ml = analysis.get("ml") or {}
    br = analysis.get("business_rules") or {}
    recs = analysis.get("portfolio_recommendations") or {}
    meta = {
        "reason": reason,
        "data_source": source_line,
        "runtime_mode": _ml_runtime_mode(),
        "n_trades": analysis.get("n_trades", 0),
        "n_active": analysis.get("n_active", 0),
        "ml_accuracy": ml.get("accuracy_test"),
        "direction_violations": len(br.get("direction_violations") or []),
        "underwater_on_recommendation": recs.get("underwater_on_recommendation", 0),
        "same_day_ok": br.get("same_day_ok"),
        "recommended_dow": br.get("recommended_dow"),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **_clients_data_freshness(),
    }
    duration = time.time() - t0
    _set_result(html_out, meta, duration, closed_history_html=closed_history_html)
    logger.info(
        "[ML] Refresh done (%s) in %.1fs — %s trades, %s active",
        _ml_runtime_mode(),
        duration,
        meta.get("n_trades"),
        meta.get("n_active"),
    )


def run_refresh_once(*, reason: str = "subprocess") -> int:
    """Single refresh in the current process (CLI / subprocess entry). Returns 0 on success."""
    t0 = time.time()
    _set_running()
    logger.info("[ML] Refresh started (%s, mode=%s, pid=%s)", reason, _ml_runtime_mode(), os.getpid())
    try:
        with _ml_data_session() as source_line:
            logger.info("[ML] Using %s", source_line)
            _execute_refresh(reason=reason, source_line=source_line, t0=t0)
        return 0
    except Exception as e:
        logger.exception("[ML] Refresh failed")
        _set_error(str(e), time.time() - t0)
        return 1


def _run_subprocess_refresh(*, reason: str) -> None:
    t0 = time.time()
    _set_running()
    env = os.environ.copy()
    env.setdefault("ML_RF_N_JOBS", "1")
    cmd = [sys.executable, "-m", "dashboard.ml_refresh_worker", "--reason", reason]
    logger.info("[ML] Spawning subprocess refresh: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=_project_root(),
            env=env,
            timeout=_refresh_timeout_sec(),
            capture_output=True,
            text=True,
        )
        _warm_memory_from_disk()
        _heal_disk_meta()
        if proc.returncode != 0:
            tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-2000:]
            _set_error(
                f"ML subprocess exit {proc.returncode}"
                + (f": {tail}" if tail else ""),
                time.time() - t0,
            )
            logger.error("[ML] Subprocess failed: %s", tail or "(no output)")
        elif not _cache_html_path().is_file():
            _set_error("ML subprocess finished but report cache is missing", time.time() - t0)
    except subprocess.TimeoutExpired:
        _set_error(f"ML refresh timed out after {_refresh_timeout_sec()}s", time.time() - t0)
        logger.error("[ML] Subprocess refresh timed out")
    except Exception as e:
        logger.exception("[ML] Subprocess refresh failed")
        _set_error(str(e), time.time() - t0)


def refresh_now(*, reason: str = "manual") -> None:
    global _refresh_queued
    if not _refresh_lock.acquire(blocking=False):
        with _debounce_lock:
            _refresh_queued = True
        logger.info("[ML] Refresh queued (%s): another refresh is in progress", reason)
        return
    try:
        if _use_subprocess_refresh():
            _run_subprocess_refresh(reason=reason)
        else:
            run_refresh_once(reason=reason)
    finally:
        _refresh_lock.release()
        follow_up = False
        with _debounce_lock:
            if _refresh_queued:
                _refresh_queued = False
                follow_up = True
        if follow_up:
            threading.Thread(
                target=lambda: refresh_now(reason="queued"),
                daemon=True,
                name="ml-predictions-followup",
            ).start()


def _interval_worker_loop() -> None:
    """Legacy: fixed timer between full rebuilds."""
    mode = _ml_runtime_mode()
    _heal_disk_meta()
    _warm_memory_from_disk()
    with _lock:
        _state["refresh_mode"] = "interval"
        _state["refresh_interval_sec"] = _interval_sec()
    logger.info(
        "[ML] Interval worker mode=%s every %ss cache=%s",
        mode,
        _interval_sec(),
        _cache_dir(),
    )
    delay = _startup_delay_sec()
    if delay and _stop_event.wait(delay):
        return
    while not _stop_event.is_set():
        refresh_now(reason="scheduled")
        if _stop_event.wait(_interval_sec()):
            break


def _watch_worker_loop() -> None:
    """Poll DB fingerprint + wake on save; debounce heavy ML rebuilds."""
    global _last_db_fingerprint, _last_scheduled_refresh_at

    mode = _ml_runtime_mode()
    _heal_disk_meta()
    _warm_memory_from_disk()
    poll = _watch_poll_sec()
    debounce = _debounce_sec()
    fallback = _fallback_interval_sec()
    with _lock:
        _state["refresh_mode"] = "watch"
        _state["watch_poll_sec"] = poll
        _state["debounce_sec"] = debounce
        _state["refresh_interval_sec"] = debounce

    logger.info(
        "[ML] Watch worker mode=%s poll=%.1fs debounce=%.1fs fallback=%ss cache=%s host=%s",
        mode,
        poll,
        debounce,
        fallback,
        _cache_dir(),
        urlparse(os.environ.get("DATABASE_URL", "")).hostname or "(from app)",
    )

    delay = _startup_delay_sec()
    if delay and _stop_event.wait(delay):
        return

    _last_db_fingerprint = _read_db_fingerprint()
    refresh_now(reason="startup")
    _last_db_fingerprint = _read_db_fingerprint()
    _last_scheduled_refresh_at = time.time()

    while not _stop_event.is_set():
        woke = _data_changed_event.wait(timeout=poll)
        if _stop_event.is_set():
            break
        if woke:
            _data_changed_event.clear()

        fp = _read_db_fingerprint()
        if fp != _last_db_fingerprint:
            _on_db_fingerprint_changed("watch" if not woke else "notify")

        if fallback > 0:
            since = time.time() - _last_scheduled_refresh_at
            if since >= fallback:
                logger.info("[ML] Fallback refresh (%.0fs since last scheduled)", since)
                _schedule_debounced_refresh("fallback")


def _worker_loop() -> None:
    if _use_watch_mode():
        _watch_worker_loop()
    else:
        _interval_worker_loop()


def _try_acquire_leader() -> bool:
    """
    On uWSGI with multiple workers, only one process runs the ML refresh loop.
    Uses non-blocking flock on Linux (PythonAnywhere); falls back to uwsgi.worker_id().
    """
    global _leader_lock_handle
    if os.environ.get("ML_PREDICTIONS_LEADER", "").strip().lower() in ("0", "false", "no"):
        return False

    lock_path = _leader_lock_path()
    try:
        import fcntl

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _leader_lock_handle = fh
        logger.info("[ML] Leader lock acquired (%s)", lock_path)
        return True
    except OSError:
        logger.info("[ML] Not leader (lock held by another worker): %s", lock_path)
        return False
    except ImportError:
        pass

    try:
        import uwsgi

        wid = int(uwsgi.worker_id())
        if wid != 1:
            logger.info("[ML] Not leader (uwsgi.worker_id=%s)", wid)
            return False
        logger.info("[ML] Leader via uwsgi.worker_id()=1")
        return True
    except ImportError:
        logger.info("[ML] Leader (single-process / dev, no flock/uwsgi)")
        return True


def start_ml_predictions_worker() -> Optional[threading.Thread]:
    global _worker_started
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return None
    if not _try_acquire_leader():
        logger.info("[ML] Background worker skipped (another uWSGI worker is leader)")
        return None
    with _worker_lock:
        if _worker_started:
            return None
        _worker_started = True
    if os.environ.get("ML_PREDICTIONS_ENABLED", "true").lower() in ("0", "false", "no"):
        logger.info("[ML] Background worker disabled (ML_PREDICTIONS_ENABLED=false)")
        return None
    _stop_event.clear()
    _load_env()
    logger.info("[ML] Cache directory: %s", _cache_dir())
    t = threading.Thread(target=_worker_loop, daemon=True, name="ml-predictions")
    t.start()
    return t
