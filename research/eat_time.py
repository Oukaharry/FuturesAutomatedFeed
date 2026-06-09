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


def entry_times_to_eat(
    entry_time: pd.Series,
    utc_correction_sec: pd.Series,
) -> pd.Series:
    """
    Map stored round-trip entry_time → true EAT for hour heatmaps.

    Plexy MT5 (utc_correction_sec == 0): naive entry_time wall clock is already
    EAT — do not add +3h (that wrongly buckets 21:00 trades into 00:00 EAT).

    Calibrated clients: naive entry_time is UTC after per-client correction →
    localize UTC then convert to EAT.
    """
    naive = pd.to_datetime(entry_time, errors="coerce")
    out = pd.Series(pd.NaT, index=naive.index, dtype="datetime64[ns, Africa/Nairobi]")
    corr = pd.to_numeric(utc_correction_sec, errors="coerce").fillna(0).astype(int)
    mask_zero = corr == 0
    if mask_zero.any():
        sub = naive.loc[mask_zero]
        out.loc[mask_zero] = sub.dt.tz_localize(
            EAT, ambiguous=True, nonexistent="shift_forward"
        )
    if (~mask_zero).any():
        sub = naive.loc[~mask_zero]
        out.loc[~mask_zero] = sub.dt.tz_localize(
            "UTC", ambiguous=True, nonexistent="shift_forward"
        ).dt.tz_convert(EAT)
    return out


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


def m1_bar_epoch_to_eat(bar_time: int) -> datetime:
    """
    Plexy MT5 M1 bar_time: Unix epoch whose UTC wall-clock digits match EAT trading time.
    (Same convention as fmtBarTs in ml_predictions.html — do NOT add +3h on convert.)
    """
    from datetime import timezone as tz

    dt = datetime.fromtimestamp(int(bar_time), tz=tz.utc)
    return datetime(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        tzinfo=EAT,
    )


def m1_bar_epoch_to_eat_ts(bar_time: int) -> pd.Timestamp:
    eat = m1_bar_epoch_to_eat(bar_time)
    return pd.Timestamp(eat)


def eat_hour_from_m1_index(ts: pd.Timestamp) -> int:
    """EAT hour from an M1 bar index (handles both true-EAT and legacy UTC+3 indexes)."""
    if ts.tzinfo is None:
        return int(ts.hour)
    eat = ts.tz_convert(EAT)
    return int(eat.hour)


def m1_bar_age_seconds(bar_time: int) -> Optional[int]:
    """Seconds since an MT5 M1 bar_time (Plexy UTC-wall-clock = EAT trading time)."""
    if not bar_time:
        return None
    try:
        eat = m1_bar_epoch_to_eat(int(bar_time))
        return max(0, int((now_eat() - eat).total_seconds()))
    except (TypeError, ValueError, OSError):
        return None
