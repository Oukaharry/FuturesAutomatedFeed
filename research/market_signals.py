"""OHLC feature engineering from M1 bars (resample + technical signals, EAT session)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from research.eat_time import EAT, format_hour_eat

# Trade entry window in Nairobi (EAT): 02:00 through 20:00 inclusive.
EAT_SESSION_START_HOUR = 2
EAT_SESSION_END_HOUR = 20

TIMEFRAME_RULES: Dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
}

BASE_TIMEFRAME = "15m"


def bars_list_to_m1_df(bars: List[dict]) -> pd.DataFrame:
    """Normalize companion / DB M1 rows to a UTC-indexed OHLCV frame."""
    if not bars:
        return pd.DataFrame()
    rows = []
    for b in bars:
        if not b:
            continue
        t = int(b.get("bar_time") or b.get("time") or 0)
        if t <= 0:
            continue
        rows.append(
            {
                "bar_time": t,
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "tick_volume": int(b.get("tick_volume") or b.get("volume") or 0),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("bar_time").drop_duplicates("bar_time", keep="last")
    df["datetime"] = pd.to_datetime(df["bar_time"], unit="s", utc=True)
    return df.set_index("datetime").sort_index()


def resample_ohlc(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    if m1.empty:
        return pd.DataFrame()
    ohlc = m1[["open", "high", "low", "close"]].resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    if "tick_volume" in m1.columns:
        ohlc["tick_volume"] = m1["tick_volume"].resample(rule).sum()
    return ohlc.dropna(subset=["close"])


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def add_bar_features(ohlc: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """Per-timeframe technical features (no lookahead)."""
    if ohlc.empty:
        return pd.DataFrame()
    out = ohlc.copy()
    c = out["close"]
    p = f"{prefix}_" if prefix else ""

    out[f"{p}ret_1"] = c.pct_change(1)
    out[f"{p}ret_4"] = c.pct_change(4)
    out[f"{p}ret_12"] = c.pct_change(12)
    out[f"{p}rsi_14"] = _rsi(c, 14)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    out[f"{p}ema9"] = ema9
    out[f"{p}ema21"] = ema21
    out[f"{p}ema_cross"] = (ema9 > ema21).astype(float)
    atr = _atr(out["high"], out["low"], c, 14)
    out[f"{p}atr_pct"] = np.where(c > 0, atr / c, 0.0)
    out[f"{p}body_pct"] = np.where(c.shift(1) > 0, (c - out["open"]) / c.shift(1), 0.0)
    out[f"{p}range_pct"] = np.where(c > 0, (out["high"] - out["low"]) / c, 0.0)

    eat = out.index.tz_convert(EAT)
    out[f"{p}hour_eat"] = eat.hour
    out[f"{p}dow_eat"] = eat.dayofweek
    out[f"{p}in_session"] = (
        (out[f"{p}hour_eat"] >= EAT_SESSION_START_HOUR)
        & (out[f"{p}hour_eat"] <= EAT_SESSION_END_HOUR)
    ).astype(float)
    return out


def _feature_cols(prefix: str) -> List[str]:
    p = f"{prefix}_" if prefix else ""
    return [
        f"{p}ret_1",
        f"{p}ret_4",
        f"{p}ret_12",
        f"{p}rsi_14",
        f"{p}ema_cross",
        f"{p}atr_pct",
        f"{p}body_pct",
        f"{p}range_pct",
        f"{p}hour_eat",
        f"{p}dow_eat",
        f"{p}in_session",
    ]


def build_multi_timeframe_features(m1: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Build a feature matrix on the 15m grid with higher-TF context merged via as-of join.
    Returns (features_df, feature_column_names).
    """
    if m1.empty or len(m1) < 200:
        return pd.DataFrame(), []

    base_rule = TIMEFRAME_RULES[BASE_TIMEFRAME]
    base_ohlc = resample_ohlc(m1, base_rule)
    if len(base_ohlc) < 100:
        return pd.DataFrame(), []

    base_feat = add_bar_features(base_ohlc, prefix="m15")
    feat_cols = list(_feature_cols("m15"))

    merged = base_feat[feat_cols + ["close"]].copy()

    for tf_key, rule in TIMEFRAME_RULES.items():
        if tf_key == BASE_TIMEFRAME:
            continue
        ohlc = resample_ohlc(m1, rule)
        if len(ohlc) < 30:
            continue
        tf_feat = add_bar_features(ohlc, prefix=tf_key)
        cols = [c for c in _feature_cols(tf_key) if c in tf_feat.columns]
        if not cols:
            continue
        side = tf_feat[cols].reset_index().rename(columns={"datetime": "dt"})
        left = merged.reset_index().rename(columns={"datetime": "dt"})
        joined = pd.merge_asof(
            left.sort_values("dt"),
            side.sort_values("dt"),
            on="dt",
            direction="backward",
        )
        merged = joined.set_index("dt")
        feat_cols.extend(cols)

    merged = merged.dropna(subset=feat_cols, how="all")
    return merged, feat_cols


def forward_return_label(
    close: pd.Series,
    horizon_bars: int,
    min_move_pct: float = 0.0008,
) -> pd.Series:
    """
    1 = BUY (price rises enough), 0 = SELL (price falls enough).
    Rows with |move| below min_move_pct are NaN (excluded from training).
    """
    fwd = close.shift(-horizon_bars) / close - 1.0
    label = pd.Series(np.nan, index=close.index, dtype=float)
    label[fwd > min_move_pct] = 1.0
    label[fwd < -min_move_pct] = 0.0
    return label


def session_mask_eat(index: pd.DatetimeIndex) -> pd.Series:
    hours = index.tz_convert(EAT).hour
    return pd.Series(
        (hours >= EAT_SESSION_START_HOUR) & (hours <= EAT_SESSION_END_HOUR),
        index=index,
    )


def best_entry_hours_from_hour_stats(
    hour_stats: List[dict],
    *,
    top_n: int = 3,
) -> List[int]:
    """Pick top EAT hours inside session by backtest hit rate."""
    eligible = [
        h
        for h in hour_stats
        if EAT_SESSION_START_HOUR <= int(h.get("hour", -1)) <= EAT_SESSION_END_HOUR
        and int(h.get("n", 0)) >= 5
    ]
    eligible.sort(key=lambda x: (float(x.get("hit_rate", 0)), int(x.get("n", 0))), reverse=True)
    return [int(h["hour"]) for h in eligible[:top_n]]


def format_entry_window(hours: List[int]) -> str:
    if not hours:
        return "—"
    return ", ".join(format_hour_eat(h) for h in sorted(hours))
