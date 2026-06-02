"""
MT5 deal time → Kenya (EAT) conversion with optional per-client calibration.

We do not persist broker ``TERMINAL_GMT_OFFSET`` today. Deals store:
  - ``time_raw``: Unix seconds from the MetaTrader5 API (treat as UTC instant)
  - ``time``: ISO string from the desktop push (legacy: PC-local wall clock; new: UTC with Z)

Calibration estimates a fixed correction (seconds) per client when legacy rows disagree.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from research.eat_time import EAT, format_hour_eat

# Target analytics timezone (Kenya desk).
ANALYTICS_TZ = EAT

# Ignore absurd skew samples (bad rows / missing fields).
_MAX_SKEW_SEC = 14 * 3600
_MIN_SAMPLES = 8


def _pc_utc_offset_sec() -> int:
    """Push machine offset from UTC (seconds east positive). Kenya ≈ +10800."""
    now = datetime.now().astimezone()
    off = now.utcoffset()
    return int(off.total_seconds()) if off is not None else 0


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
    Estimate seconds to add to ``time_raw`` (as UTC) so wall ``time`` ISO matches EAT intent.

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
) -> Dict[str, Any]:
    """
    Snapshot to store on each dashboard push (``identity.mt5_timing``).

    Not the broker's official offset (Python MT5 API does not expose TERMINAL_GMT_OFFSET),
    but enough to calibrate ML analytics to Kenya wall time.
    """
    ctx: Dict[str, Any] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "analytics_tz": "Africa/Nairobi",
        "pc_utc_offset_sec": _pc_utc_offset_sec(),
        "time_raw_semantics": "mt5_unix_utc",
        "time_iso_semantics": "utc_z_when_suffixed_else_eat_wall_legacy",
    }
    if account:
        ctx["mt5_server"] = account.get("server") or ""
        ctx["mt5_company"] = account.get("company") or ""
        ctx["mt5_login"] = account.get("login")
    deals = sample_deals or []
    correction, diag = infer_utc_correction_sec(deals)
    ctx["utc_correction_sec"] = correction
    ctx["calibration"] = diag
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
    parts = ["Entry hours: East Africa Time (Africa/Nairobi, UTC+3)"]
    if corr:
        parts.append(f"per-client calibration {corr / 3600:+.1f}h on Unix timestamps")
    cal = timing.get("calibration") or {}
    if cal.get("samples"):
        parts.append(f"({cal['samples']} deal samples at last push)")
    return ". ".join(parts) + "."
