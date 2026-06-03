"""East Africa Time (Kenya, EAT = UTC+3) for ML reports and trading-day rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

try:
    EAT = ZoneInfo("Africa/Nairobi")
except Exception:  # pragma: no cover — missing tzdata on some hosts
    # Kenya has no DST; fixed UTC+3 matches Nairobi civil time.
    EAT = timezone(timedelta(hours=3), name="EAT")

DOW_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Mon–Fri only (no weekend trading; matches dashboard _should_skip_daily_summary_tracking).
TRADING_WEEKDAY_NAMES = frozenset(DOW_NAMES[:5])


def now_eat() -> datetime:
    return datetime.now(EAT)


def today_eat_date_str() -> str:
    return now_eat().date().isoformat()


def today_eat_dow_name() -> str:
    return DOW_NAMES[now_eat().weekday()]


def is_trading_weekday_name(name: str) -> bool:
    return str(name or "") in TRADING_WEEKDAY_NAMES


def is_trading_day_eat() -> bool:
    """True on Mon–Fri in Kenya (EAT); False on Saturday/Sunday."""
    return now_eat().weekday() < 5


def coordinated_entry_dow_name() -> str:
    """
    Actionable coordinated entry day in EAT.
    Weekends map to the next session (Monday), not calendar Saturday/Sunday.
    """
    today = today_eat_dow_name()
    if is_trading_weekday_name(today):
        return today
    return "Monday (next EAT session)"


def to_eat_series(series: pd.Series) -> pd.Series:
    """
    Normalize timestamps to EAT for hour/DOW and calendar date.

    tz-aware values are converted to EAT. Naive values are treated as UTC wall
    time (round-trip entry_time from trade_dataset is stored as UTC-naive).
    """
    s = pd.to_datetime(series, errors="coerce", utc=True)
    if getattr(s.dt, "tz", None) is None:
        s = s.dt.tz_localize("UTC", ambiguous=True, nonexistent="shift_forward")
    return s.dt.tz_convert(EAT)


def eat_dow_name(series_eat: pd.Series) -> pd.Series:
    """Day-of-week name from EAT-localized timestamps."""
    dow = series_eat.dt.dayofweek
    return dow.map(lambda i: DOW_NAMES[int(i)] if 0 <= int(i) < 7 else "?")


def format_dt_eat(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return "—"
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC", ambiguous=True, nonexistent="shift_forward")
        return ts.tz_convert(EAT).strftime("%Y-%m-%d %H:%M EAT")
    except Exception:
        return str(val)[:22]


def format_hour_eat(h: object) -> str:
    try:
        hi = int(h)
        if 0 <= hi <= 23:
            return f"{hi:02d}:00 EAT"
    except (TypeError, ValueError):
        pass
    return "—"
