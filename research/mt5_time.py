"""
MT5 deal time → Kenya (EAT) conversion with live TimeCurrent vs Nairobi calibration.

On push, the desktop app compares MQL5 *TimeCurrent* (tick-time proxy) to Nairobi wall
clock and stores the offset in ``identity.mt5_timing``. Historical deals use that offset
plus dual-field inference when needed.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from research.eat_time import EAT, format_hour_eat

# Target analytics timezone (Kenya desk).
ANALYTICS_TZ = EAT

# Symbols to probe for TimeCurrent() proxy (last tick time).
_LIQUID_SYMBOLS = (
    "US100",
    "NAS100",
    "USTEC",
    "NQ100",
    "SPX500",
    "EURUSD",
    "XAUUSD",
    "GOLD",
    "BTCUSD",
)

# Ignore absurd skew samples (bad rows / missing fields).
_MAX_SKEW_SEC = 14 * 3600
_MIN_SAMPLES = 8
_MAX_TICK_STALE_SEC = 300


def _pc_utc_offset_sec() -> int:
    """Push machine offset from UTC (seconds east positive). Kenya ≈ +10800."""
    now = datetime.now().astimezone()
    off = now.utcoffset()
    return int(off.total_seconds()) if off is not None else 0


def _normalize_sod_delta(seconds: int) -> int:
    """Normalize wall-clock delta to (-12h, +12h]."""
    while seconds > 43200:
        seconds -= 86400
    while seconds <= -43200:
        seconds += 86400
    return seconds


def _wall_sod(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def timecurrent_proxy_unix(mt5: Any) -> Tuple[Optional[str], Optional[int]]:
    """
    MQL5 ``TimeCurrent()`` proxy when Python API has no direct call.

    Uses the latest tick (or M1 bar open) on a liquid symbol — same clock MT5 uses
    for "server time" while quotes are flowing.
    """
    for sym in _LIQUID_SYMBOLS:
        try:
            if mt5.symbol_select(sym, True):
                tick = mt5.symbol_info_tick(sym)
                if tick and int(tick.time) > 0:
                    return sym, int(tick.time)
        except Exception:
            continue
    for sym in _LIQUID_SYMBOLS:
        try:
            if mt5.symbol_select(sym, True):
                rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 1)
                if rates is not None and len(rates):
                    return sym, int(rates[0]["time"])
        except Exception:
            continue
    return None, None


def measure_timecurrent_vs_nairobi(mt5: Any) -> Dict[str, Any]:
    """
    Compare MT5 server clock (TimeCurrent proxy) to Nairobi (EAT) at capture instant.

    MQL5 ``TimeCurrent()`` returns broker *server* wall time. Many brokers encode that
    clock in Unix fields (``deal.time`` / tick time). We compare:

    - **Server wall**: ``utcfromtimestamp(TimeCurrent_proxy)`` (broker clock digits)
    - **Nairobi wall**: ``datetime.now(Africa/Nairobi)``

    The difference (seconds, modulo 24h) is stored as ``mt5_server_minus_nairobi_wall_sec``.
    Deal timestamps get ``utc_correction_sec`` so ML entry hours land in EAT.
    """
    eat_now = datetime.now(EAT)
    utc_now = datetime.now(timezone.utc)
    sym, tc_unix = timecurrent_proxy_unix(mt5)
    out: Dict[str, Any] = {
        "method": "timecurrent_vs_nairobi",
        "nairobi_iso": eat_now.isoformat(),
        "utc_iso": utc_now.isoformat(),
        "nairobi_utc_offset_sec": int(eat_now.utcoffset().total_seconds()),
    }
    if not tc_unix:
        out["error"] = "no_timecurrent_proxy (MT5 not connected or no quotes)"
        return out

    server_wall = datetime.utcfromtimestamp(tc_unix)
    nairobi_wall = eat_now.replace(tzinfo=None)
    server_minus_nairobi = _normalize_sod_delta(
        _wall_sod(server_wall) - _wall_sod(nairobi_wall)
    )

    tc_utc = datetime.fromtimestamp(tc_unix, tz=timezone.utc)
    tc_eat = tc_utc.astimezone(EAT)
    freshness = int(tc_unix - utc_now.timestamp())

    # PC-local wall (Kenya machine) vs Nairobi — should be ~0 if OS is on EAT.
    try:
        pc_local = datetime.fromtimestamp(tc_unix)
        if pc_local.tzinfo is not None:
            pc_local = pc_local.astimezone(EAT).replace(tzinfo=None)
        pc_minus_nairobi = _normalize_sod_delta(_wall_sod(pc_local) - _wall_sod(nairobi_wall))
    except (OSError, ValueError):
        pc_minus_nairobi = None

    utc_wall = tc_utc.replace(tzinfo=None)
    server_utc_offset = _normalize_sod_delta(_wall_sod(server_wall) - _wall_sod(utc_wall))

    # Shift Unix deal stamps (broker server clock) → align to Nairobi wall for analytics.
    utc_correction = int(server_minus_nairobi)

    out.update(
        {
            "timecurrent_symbol": sym,
            "timecurrent_unix": tc_unix,
            "timecurrent_utc": tc_utc.isoformat(),
            "timecurrent_eat_from_true_utc": tc_eat.isoformat(),
            "server_wall_naive": server_wall.strftime("%Y-%m-%d %H:%M:%S"),
            "nairobi_wall_naive": nairobi_wall.strftime("%Y-%m-%d %H:%M:%S"),
            "mt5_server_minus_nairobi_wall_sec": server_minus_nairobi,
            "mt5_server_minus_nairobi_hours": round(server_minus_nairobi / 3600.0, 2),
            "mt5_server_utc_offset_sec": server_utc_offset,
            "pc_local_minus_nairobi_wall_sec": pc_minus_nairobi,
            "tick_freshness_sec": freshness,
            "utc_correction_sec": utc_correction,
            "stale_tick": abs(freshness) > _MAX_TICK_STALE_SEC,
        }
    )
    return out


def _parse_iso_wall(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        ts = pd.Timestamp(s)
        if ts.tz is None:
            # Legacy companion: naive ISO is Kenya wall clock at push.
            ts = ts.tz_localize(ANALYTICS_TZ, ambiguous=True, nonexistent="shift_forward")
        return ts.tz_convert("UTC")
    except (ValueError, TypeError):
        return None


def _instant_from_time_raw(time_raw: Any, correction_sec: int = 0) -> Optional[pd.Timestamp]:
    try:
        t = float(time_raw)
        if t <= 0:
            return None
        ts = pd.Timestamp(t, unit="s", tz="UTC")
        if correction_sec:
            ts = ts + pd.Timedelta(seconds=int(correction_sec))
        return ts
    except (TypeError, ValueError, OSError):
        return None


def infer_utc_correction_sec(
    deals: List[dict],
    *,
    max_samples: int = 400,
) -> Tuple[int, Dict[str, Any]]:
    """
    Fallback: estimate seconds to add to ``time_raw`` from ``time`` ISO vs Unix.

    Returns (correction_sec, diagnostics).
    """
    skews: List[float] = []
    used = 0
    for deal in deals:
        if used >= max_samples:
            break
        if not isinstance(deal, dict):
            continue
        raw = deal.get("time_raw")
        iso = deal.get("time")
        if raw is None or iso is None or str(iso).strip() == "":
            continue
        t_utc = _instant_from_time_raw(raw, 0)
        t_wall = _parse_iso_wall(iso)
        if t_utc is None or t_wall is None:
            continue
        skew = (t_wall - t_utc).total_seconds()
        if abs(skew) > _MAX_SKEW_SEC:
            continue
        skews.append(skew)
        used += 1

    diag: Dict[str, Any] = {
        "samples": len(skews),
        "method": "median_iso_minus_utc_raw",
    }
    if len(skews) < _MIN_SAMPLES:
        diag["reason"] = f"need {_MIN_SAMPLES}+ dual-field deals, have {len(skews)}"
        return 0, diag

    correction = int(round(statistics.median(skews)))
    diag["correction_sec"] = correction
    diag["correction_hours"] = round(correction / 3600.0, 2)
    try:
        diag["stdev_hours"] = round(statistics.pstdev(skews) / 3600.0, 2)
    except statistics.StatisticsError:
        diag["stdev_hours"] = 0.0
    return correction, diag


def capture_push_timing_context(
    *,
    account: Optional[Dict[str, Any]] = None,
    sample_deals: Optional[List[dict]] = None,
    mt5: Any = None,
) -> Dict[str, Any]:
    """
    Snapshot stored on each dashboard push (``identity.mt5_timing``).

    Prefer live ``TimeCurrent`` vs Nairobi when MT5 is connected; fall back to deal inference.
    """
    ctx: Dict[str, Any] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "analytics_tz": "Africa/Nairobi",
        "pc_utc_offset_sec": _pc_utc_offset_sec(),
        "time_raw_semantics": "mt5_unix_server_or_utc",
        "time_iso_semantics": "utc_z_when_suffixed_else_eat_wall_legacy",
    }
    if account:
        ctx["mt5_server"] = account.get("server") or ""
        ctx["mt5_company"] = account.get("company") or ""
        ctx["mt5_login"] = account.get("login")

    live: Dict[str, Any] = {}
    if mt5 is not None:
        try:
            live = measure_timecurrent_vs_nairobi(mt5)
            ctx["timecurrent_probe"] = live
        except Exception as exc:
            live = {"error": str(exc)}
            ctx["timecurrent_probe"] = live

    deals = sample_deals or []
    deal_correction, deal_diag = infer_utc_correction_sec(deals)

    if live and not live.get("error") and not live.get("stale_tick"):
        ctx["utc_correction_sec"] = int(live.get("utc_correction_sec") or 0)
        ctx["calibration"] = {
            "method": "timecurrent_vs_nairobi",
            "server_minus_nairobi_hours": live.get("mt5_server_minus_nairobi_hours"),
            "tick_freshness_sec": live.get("tick_freshness_sec"),
            "timecurrent_symbol": live.get("timecurrent_symbol"),
        }
    else:
        ctx["utc_correction_sec"] = deal_correction
        ctx["calibration"] = deal_diag
        if live.get("stale_tick"):
            ctx["calibration"]["timecurrent_stale"] = True
            ctx["calibration"]["fallback"] = "deal_inference"

    ctx["deal_inference_correction_sec"] = deal_correction
    ctx["deal_inference"] = deal_diag
    return ctx


def timing_for_client(identity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read stored timing from client identity / mt5_timing blob."""
    if not identity:
        return {}
    raw = identity.get("mt5_timing")
    if isinstance(raw, dict):
        return raw
    return {}


def deal_instant_utc(
    deal: dict,
    *,
    correction_sec: int = 0,
) -> Optional[pd.Timestamp]:
    """
    Best-effort true instant (UTC) for a deal.

    Prefer ``time_raw`` + correction; fall back to ``time`` ISO.
    """
    raw = deal.get("time_raw")
    if raw is not None and str(raw).strip() not in ("", "0"):
        ts = _instant_from_time_raw(raw, correction_sec)
        if ts is not None:
            return ts
    return _parse_iso_wall(deal.get("time"))


def deal_instant_eat(
    deal: dict,
    *,
    correction_sec: int = 0,
) -> Optional[pd.Timestamp]:
    ts = deal_instant_utc(deal, correction_sec=correction_sec)
    return ts.tz_convert(ANALYTICS_TZ) if ts is not None else None


def eat_hour_from_deal(deal: dict, *, correction_sec: int = 0) -> int:
    ts = deal_instant_eat(deal, correction_sec=correction_sec)
    return int(ts.hour) if ts is not None else -1


def format_timing_note(timing: Dict[str, Any]) -> str:
    corr = int(timing.get("utc_correction_sec") or 0)
    cal = timing.get("calibration") or {}
    method = cal.get("method", "")
    parts = ["Entry hours: East Africa Time (Africa/Nairobi, UTC+3)"]
    if method == "timecurrent_vs_nairobi":
        hrs = cal.get("server_minus_nairobi_hours")
        if hrs is not None:
            parts.append(f"MT5 server vs Nairobi {hrs:+.1f}h (TimeCurrent probe)")
        if corr:
            parts.append(f"deal timestamp shift {corr / 3600:+.1f}h")
    elif corr:
        parts.append(f"per-client calibration {corr / 3600:+.1f}h on Unix timestamps")
    if cal.get("samples"):
        parts.append(f"({cal['samples']} deal samples)")
    return ". ".join(parts) + "."
