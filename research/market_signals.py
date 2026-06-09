"""OHLC feature engineering from M1 bars (resample + technical signals, EAT session)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from research.eat_time import EAT, format_hour_eat, m1_bar_epoch_to_eat_ts

# Market / ML session in Nairobi (EAT): 02:00 through 20:00 inclusive.
EAT_SESSION_START_HOUR = 2
EAT_SESSION_END_HOUR = 20

# Reference desk entry band (for outside-window labels / timestamp validation only).
EAT_ENTRY_START_HOUR = 2
EAT_ENTRY_END_HOUR = 17

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
    # Plexy MT5: unix UTC wall clock = EAT trading time (see fmtBarTs in ml_predictions.html)
    eat_index = [m1_bar_epoch_to_eat_ts(int(t)) for t in df["bar_time"]]
    df.index = pd.DatetimeIndex(eat_index, name="datetime")
    return df.sort_index()


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


def compute_intraday_momentum(m1: pd.DataFrame) -> Dict[str, Any]:
    """
    Short-horizon direction from latest M1 (catches morning reversals the 15m model misses).
    Uses last 15 / 30 / 60 minutes of closes inside EAT session.
    """
    empty: Dict[str, Any] = {
        "bias": "NEUTRAL",
        "strength": 0.0,
        "ret_15m_pct": 0.0,
        "ret_30m_pct": 0.0,
        "ret_60m_pct": 0.0,
        "ema5m_cross": 0,
        "note": "no data",
    }
    if m1.empty or len(m1) < 20:
        return empty

    c = m1["close"].astype(float)
    last = float(c.iloc[-1])

    def _ret(n: int) -> float:
        if len(c) <= n:
            return 0.0
        base = float(c.iloc[-1 - n])
        return (last / base - 1.0) if base > 0 else 0.0

    r15 = _ret(15)
    r30 = _ret(30)
    r60 = _ret(min(60, len(c) - 1))

    ohlc5 = resample_ohlc(m1.tail(max(120, len(m1))), "5min")
    ema_cross = 0
    if len(ohlc5) >= 21:
        ema9 = _ema(ohlc5["close"], 9)
        ema21 = _ema(ohlc5["close"], 21)
        ema_cross = 1 if float(ema9.iloc[-1]) > float(ema21.iloc[-1]) else -1

    # Weight recent moves; 5m EMA tie-break
    score = r15 * 3.0 + r30 * 2.0 + r60 * 1.0 + ema_cross * 0.0005
    threshold = 0.0004  # ~0.04% composite move

    if score > threshold:
        bias = "BUY"
    elif score < -threshold:
        bias = "SELL"
    else:
        bias = "NEUTRAL"

    strength = min(1.0, abs(score) / max(threshold * 3, 1e-9))

    return {
        "bias": bias,
        "strength": round(strength, 4),
        "ret_15m_pct": round(r15 * 100, 4),
        "ret_30m_pct": round(r30 * 100, 4),
        "ret_60m_pct": round(r60 * 100, 4),
        "ema5m_cross": ema_cross,
        "note": f"15m {r15 * 100:+.3f}% · 30m {r30 * 100:+.3f}% · 5m EMA {'bull' if ema_cross > 0 else 'bear'}",
    }


def live_book_contradiction(active_df: pd.DataFrame, bias: str) -> Dict[str, Any]:
    """
    Detect when open float P/L clearly disagrees with the recommended side.
    E.g. SELL rec but BUY legs winning and SELL legs losing → market moved up.
    """
    out: Dict[str, Any] = {"contradicts": False, "suggested_side": None, "note": ""}
    if active_df is None or active_df.empty or bias not in ("BUY", "SELL"):
        return out

    side_col = "side" if "side" in active_df.columns else None
    pnl_col = "profit" if "profit" in active_df.columns else "net_pnl" if "net_pnl" in active_df.columns else None
    if not side_col or not pnl_col:
        return out

    opp = "BUY" if bias == "SELL" else "SELL"
    aligned = active_df[active_df[side_col].astype(str).str.upper() == bias]
    misaligned = active_df[active_df[side_col].astype(str).str.upper() == opp]
    if aligned.empty or misaligned.empty:
        return out

    try:
        aligned_pnl = float(aligned[pnl_col].astype(float).sum())
        misaligned_pnl = float(misaligned[pnl_col].astype(float).sum())
        aligned_losing = int((aligned[pnl_col].astype(float) < 0).sum())
        misaligned_winning = int((misaligned[pnl_col].astype(float) > 0).sum())
    except (TypeError, ValueError):
        return out

    if (
        aligned_losing >= 2
        and misaligned_winning >= 2
        and aligned_pnl < 0
        and misaligned_pnl > 0
        and misaligned_pnl > abs(aligned_pnl) * 0.5
    ):
        out["contradicts"] = True
        out["suggested_side"] = opp
        out["note"] = (
            f"Live book: {bias} legs ${aligned_pnl:,.0f} ({aligned_losing} underwater) vs "
            f"{opp} legs ${misaligned_pnl:,.0f} ({misaligned_winning} winning) — market likely {opp}."
        )
    return out
