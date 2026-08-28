"""
Shared API response cache (Postgres L2 + in-process L1).

Serves fresh cache immediately. On expiry, returns stale data and refreshes
in a background thread so request workers stay free (avoids 502-backend).
On a true miss, one worker claims the compute; everyone else gets 503 quickly.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_table_ready = False
_table_lock = threading.Lock()
_local: dict[str, tuple[Any, float]] = {}
_local_guard = threading.Lock()
_key_locks_guard = threading.Lock()
_refreshing: set[str] = set()

# Default TTLs (seconds). Keep long enough that super_admin reloads hit L2.
HIERARCHY_CACHE_TTL = 300
SUPER_ADMIN_TOTALS_CACHE_TTL = 300
PROFIT_SPLITS_CACHE_TTL = 180
AVG_PROFIT_SPLITS_CACHE_TTL = 180

# Marker returned when a value is not cached yet and a background compute is running.
CACHE_PENDING = object()

_CLAIM_TTL_SECONDS = 600
_CLAIM_SUFFIX = "::computing"
# Only one multi-minute scan at a time across all uWSGI workers.
HEAVY_COMPUTE_GLOBAL_KEY = "heavy_compute::global"


def _claim_key(key: str) -> str:
    return f"{key}{_CLAIM_SUFFIX}"


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        try:
            from dashboard.database import get_connection

            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_response_cache (
                        cache_key   TEXT PRIMARY KEY,
                        payload     TEXT NOT NULL,
                        expires_at  TIMESTAMPTZ NOT NULL,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_response_cache_expires
                    ON api_response_cache (expires_at)
                    """
                )
                conn.commit()
            _table_ready = True
        except Exception as e:
            logger.warning("[shared_cache] table ensure failed: %s", e)


def _local_get(key: str) -> Optional[Any]:
    now = time.time()
    with _local_guard:
        row = _local.get(key)
        if not row:
            return None
        value, expiry = row
        if now >= expiry:
            return None  # keep entry so stale reads still work
        return value


def _local_get_stale(key: str) -> Optional[Any]:
    with _local_guard:
        row = _local.get(key)
        if not row:
            return None
        return row[0]


def _local_set(key: str, value: Any, ttl: int) -> None:
    with _local_guard:
        if len(_local) > 100:
            now = time.time()
            expired = [k for k, (_, exp) in _local.items() if now >= exp]
            for k in expired:
                del _local[k]
        _local[key] = (value, time.time() + ttl)


def _local_set_stale(key: str, value: Any) -> None:
    """Keep a value in L1 that cache_get treats as expired."""
    with _local_guard:
        _local[key] = (value, time.time() - 1)


def _local_delete_prefix(prefix: str) -> None:
    with _local_guard:
        for k in list(_local.keys()):
            if k.startswith(prefix):
                del _local[k]


def cache_get(key: str) -> Optional[Any]:
    """Return cached JSON-decoded value if present and not expired."""
    hit = _local_get(key)
    if hit is not None:
        return hit

    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT payload FROM api_response_cache
                WHERE cache_key = ? AND expires_at > NOW()
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row["payload"] if hasattr(row, "keys") else row[0]
            value = json.loads(payload)
            _local_set(key, value, 30)
            return value
    except Exception as e:
        logger.debug("[shared_cache] cache_get miss %s: %s", key, e)
        return None


def cache_get_stale(key: str) -> Optional[Any]:
    """Return cached value even if TTL has expired. None if never stored."""
    hit = _local_get_stale(key)
    if hit is not None:
        return hit

    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT payload FROM api_response_cache
                WHERE cache_key = ?
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row["payload"] if hasattr(row, "keys") else row[0]
            value = json.loads(payload)
            _local_set_stale(key, value)
            return value
    except Exception as e:
        logger.debug("[shared_cache] cache_get_stale miss %s: %s", key, e)
        return None


def cache_set(key: str, value: Any, ttl: int) -> None:
    _local_set(key, value, ttl)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        payload = json.dumps(value, default=str)
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO api_response_cache (cache_key, payload, expires_at, updated_at)
                VALUES (?, ?, NOW() + (? * INTERVAL '1 second'), NOW())
                ON CONFLICT (cache_key) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                """,
                (key, payload, int(ttl)),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] cache_set failed %s: %s", key, e)


def invalidate_prefix(prefix: str) -> None:
    """Drop all keys starting with prefix (L1 + Postgres)."""
    _local_delete_prefix(prefix)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM api_response_cache WHERE cache_key LIKE ?",
                (prefix + "%",),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] invalidate_prefix failed %s: %s", prefix, e)


def invalidate_key(key: str) -> None:
    with _local_guard:
        _local.pop(key, None)
        _local.pop(_claim_key(key), None)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM api_response_cache WHERE cache_key IN (?, ?)",
                (key, _claim_key(key)),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] invalidate_key failed %s: %s", key, e)


def try_claim_compute(key: str, claim_ttl: int = _CLAIM_TTL_SECONDS) -> bool:
    """Atomically claim the right to compute `key`. True if this caller should compute."""
    _ensure_table()
    claim_key = _claim_key(key)
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO api_response_cache (cache_key, payload, expires_at, updated_at)
                VALUES (?, '"1"', NOW() + (? * INTERVAL '1 second'), NOW())
                ON CONFLICT (cache_key) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                WHERE api_response_cache.expires_at < NOW()
                RETURNING cache_key
                """,
                (claim_key, int(claim_ttl)),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None
    except Exception as e:
        logger.debug("[shared_cache] try_claim unavailable %s: %s", key, e)
        return False


def release_claim(key: str) -> None:
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM api_response_cache WHERE cache_key = ?",
                (_claim_key(key),),
            )
            conn.commit()
    except Exception:
        pass


def _compute_and_store(key: str, ttl: int, compute_fn: Callable[[], Any]) -> None:
    """Run one cache job (caller must hold per-key + global heavy claims)."""
    cached = cache_get(key)
    if cached is not None:
        return
    logger.info("[shared_cache] computing %s", key)
    started = time.time()
    value = compute_fn()
    cache_set(key, value, ttl)
    logger.info("[shared_cache] computed %s in %.1fs", key, time.time() - started)


def run_heavy_cache_job(
    key: str,
    ttl: int,
    compute_fn: Callable[[], Any],
    *,
    app=None,
) -> None:
    """Compute one cache entry with per-key + global heavy single-flight."""
    key_claimed = False
    heavy_claimed = False
    try:
        if not try_claim_compute(key):
            return
        key_claimed = True
        if cache_get(key) is not None:
            return
        if not try_claim_compute(HEAVY_COMPUTE_GLOBAL_KEY, claim_ttl=900):
            return
        heavy_claimed = True
        if cache_get(key) is not None:
            return

        def _do() -> None:
            _compute_and_store(key, ttl, compute_fn)

        if app is not None:
            with app.app_context():
                _do()
        else:
            _do()
    except Exception:
        logger.exception("[shared_cache] heavy cache job failed %s", key)
    finally:
        if heavy_claimed:
            release_claim(HEAVY_COMPUTE_GLOBAL_KEY)
        if key_claimed:
            release_claim(key)


def _schedule_refresh(key: str, ttl: int, compute_fn: Callable[[], Any]) -> None:
    """Run compute_fn in a daemon thread. One job globally at a time."""
    with _key_locks_guard:
        if key in _refreshing:
            return
        _refreshing.add(key)

    app = None
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except Exception:
        pass

    def _run() -> None:
        try:
            run_heavy_cache_job(key, ttl, compute_fn, app=app)
        finally:
            with _key_locks_guard:
                _refreshing.discard(key)

    threading.Thread(target=_run, daemon=True, name=f"cache-refresh-{key[:32]}").start()


def get_or_compute(
    key: str,
    ttl: int,
    compute_fn: Callable[[], Any],
    *,
    max_wait: float = 45.0,
) -> Any:
    """
    Return cached value, or CACHE_PENDING if a background compute is in flight.

    Never computes on the request thread. max_wait is ignored (kept for callers);
    blocking a worker for tens of seconds is what 502s the whole site.
    """
    del max_wait  # do not block workers waiting for multi-minute jobs

    cached = cache_get(key)
    if cached is not None:
        return cached

    stale = cache_get_stale(key)
    _schedule_refresh(key, ttl, compute_fn)
    if stale is not None:
        return stale

    # True miss: give a fast compute a brief chance so tests / tiny payloads
    # still return 200 on the first request.
    deadline = time.time() + 0.5
    while time.time() < deadline:
        time.sleep(0.1)
        cached = cache_get(key)
        if cached is not None:
            return cached

    return CACHE_PENDING
