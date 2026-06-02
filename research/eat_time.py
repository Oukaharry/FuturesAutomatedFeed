"""East Africa Time (Kenya, EAT = UTC+3) for ML reports and trading-day rules."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

EAT = ZoneInfo("Africa/Nairobi")

DOW_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def now_eat() -> datetime:
    return datetime.now(EAT)


def today_eat_date_str() -> str:
    return now_eat().date().isoformat()


def today_eat_dow_name() -> str:
    return DOW_NAMES[now_eat().weekday()]


def to_eat_series(series: pd.Series) -> pd.Series:
    """
    Normalize deal/position timestamps to EAT for hour/DOW and calendar date.
    Naive values are treated as UTC (MT5/server storage), then converted.
    """
    s = pd.to_datetime(series, errors="coerce")
    if s.dt.tz is None:
        s = s.dt.tz_localize("UTC", ambiguous="infer", nonexistent="shift_forward")
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
            ts = ts.tz_localize("UTC", ambiguous="infer", nonexistent="shift_forward")
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
