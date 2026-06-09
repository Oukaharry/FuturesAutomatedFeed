"""
Momentum bias from M1 USTECH + forecast windows (10m … 4h) in EAT.

No opaque classifier — multi-TF momentum vote, then measured persistence
on historical M1: "when momentum looked like this, how often did it hold for H minutes?"
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from research.eat_time import EAT, now_eat
from research.market_signals import (
    EAT_SESSION_END_HOUR,
    EAT_SESSION_START_HOUR,
    bars_list_to_m1_df,
    resample_ohlc,
    _ema,
)

# Forecast horizons the user asked for (minutes)
FORECAST_HORIZONS_MIN: Tuple[int, ...] = (10, 20, 60, 180, 240)
DEFAULT_WINDOW_MIN = 240  # 4 hours — primary entry window
MIN_MOVE_BPS = 3.0  # 0.03% min move to count as "held direction"


def _min_move_pct() -> float:
    try:
        return float(os.environ.get("ML_MOMENTUM_MIN_MOVE_BPS", str(MIN_MOVE_BPS))) / 10000.0
    except ValueError:
        return MIN_MOVE_BPS / 10000.0


def _default_window_min() -> int:
    try:
        return max(60, int(os.environ.get("ML_MOMENTUM_WINDOW_MIN", str(DEFAULT_WINDOW_MIN))))
    except ValueError:
        return DEFAULT_WINDOW_MIN


def _session_end_today_eat(now_local: pd.Timestamp) -> pd.Timestamp:
    """Today 20:00 EAT (last minute of trading window)."""
    d = now_local.date()
    return pd.Timestamp(
        year=d.year, month=d.month, day=d.day,
        hour=EAT_SESSION_END_HOUR, minute=0, tz=EAT,
    )


def _fmt_eat(ts: pd.Timestamp) -> str:
    return ts.tz_convert(EAT).strftime("%H:%M EAT")


def _fmt_eat_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
    s = start.tz_convert(EAT)
    e = end.tz_convert(EAT)
    if s.date() == e.date():
        return f"{s.strftime('%H:%M')} – {e.strftime('%H:%M EAT')}"
    return f"{s.strftime('%Y-%m-%d %H:%M')} – {e.strftime('%Y-%m-%d %H:%M EAT')}"


def _tf_momentum_vote(ohlc: pd.DataFrame) -> Tuple[int, float]:
    """+1 BUY, -1 SELL, 0 flat; second value = magnitude."""
    if ohlc.empty or len(ohlc) < 22:
        return 0, 0.0
    c = ohlc["close"].astype(float)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    ema_dir = 1 if float(ema9.iloc[-1]) > float(ema21.iloc[-1]) else -1
    ret3 = float(c.pct_change(3).iloc[-1]) if len(c) > 3 else 0.0
    ret_dir = 1 if ret3 > 0.0001 else (-1 if ret3 < -0.0001 else 0)
    slope = float((ema9.iloc[-1] - ema9.iloc[-5]) / ema9.iloc[-5]) if len(ema9) >= 5 and ema9.iloc[-5] else 0.0
    score = ema_dir * 0.5 + ret_dir * 0.35 + (1 if slope > 0 else -1 if slope < 0 else 0) * 0.15
    return (1 if score > 0.15 else -1 if score < -0.15 else 0), abs(score)


def compute_momentum_state(m1: pd.DataFrame) -> Dict[str, Any]:
    """
    Deterministic multi-TF momentum from M1 (5m / 15m / 30m / 1h votes).
    """
    empty: Dict[str, Any] = {
        "ready": False,
        "bias": "—",
        "strength": 0.0,
        "votes": {},
        "note": "insufficient M1 bars",
    }
    if m1.empty or len(m1) < 120:
        return empty

    votes: Dict[str, int] = {}
    mags: List[float] = []
    for label, rule in [("5m", "5min"), ("15m", "15min"), ("30m", "30min"), ("1h", "1h")]:
        ohlc = resample_ohlc(m1, rule)
        v, mag = _tf_momentum_vote(ohlc)
        votes[label] = v
        if v != 0:
            mags.append(mag)

    buy_v = sum(1 for v in votes.values() if v > 0)
    sell_v = sum(1 for v in votes.values() if v < 0)
    total = buy_v + sell_v

    if buy_v >= 3 and buy_v > sell_v:
        bias = "BUY"
        strength = buy_v / 4.0
    elif sell_v >= 3 and sell_v > buy_v:
        bias = "SELL"
        strength = sell_v / 4.0
    elif buy_v >= 2 and buy_v > sell_v:
        bias = "BUY"
        strength = 0.5 + buy_v * 0.1
    elif sell_v >= 2 and sell_v > buy_v:
        bias = "SELL"
        strength = 0.5 + sell_v * 0.1
    else:
        bias = "—"
        strength = 0.0

    if mags:
        strength = min(1.0, (strength + float(np.mean(mags))) / 2.0)

    c = m1["close"].astype(float)
    r15 = float(c.iloc[-1] / c.iloc[-16] - 1) if len(c) > 16 else 0.0
    note = (
        f"Votes: 5m={votes.get('5m', 0):+d} 15m={votes.get('15m', 0):+d} "
        f"30m={votes.get('30m', 0):+d} 1h={votes.get('1h', 0):+d} · M1 15m {r15 * 100:+.2f}%"
    )

    return {
        "ready": bias in ("BUY", "SELL"),
        "bias": bias,
        "strength": round(strength, 3),
        "votes": votes,
        "buy_votes": buy_v,
        "sell_votes": sell_v,
        "note": note,
    }


def _momentum_bias_at_index(m1: pd.DataFrame, end_idx: int) -> Tuple[str, float]:
    """Fast momentum vote using M1 slice ending at bar index (for backtest loop)."""
    if end_idx < 120:
        return "—", 0.0
    slice_m1 = m1.iloc[: end_idx + 1]
    state = compute_momentum_state(slice_m1)
    return str(state.get("bias") or "—"), float(state.get("strength") or 0)


def measure_horizon_persistence(
    m1: pd.DataFrame,
    current_bias: str,
    *,
    sample_every_min: int = 15,
    lookback_bars: int = 5000,
    max_samples: int = 400,
) -> List[Dict[str, Any]]:
    """
    On historical M1: when momentum state matched current_bias, how often did
    price continue that direction for each horizon?
    """
    min_move = _min_move_pct()
    horizons = FORECAST_HORIZONS_MIN
    results: List[Dict[str, Any]] = []

    if m1.empty or current_bias not in ("BUY", "SELL"):
        for h in horizons:
            results.append({"minutes": h, "label": _horizon_label(h), "bias": "—", "persistence_pct": None, "n": 0})
        return results

    work = m1.iloc[-lookback_bars:] if len(m1) > lookback_bars else m1
    closes = work["close"].astype(float).values
    times = work.index
    n = len(work)

    max_h = max(horizons)
    if n < max_h + 200:
        for h in horizons:
            results.append({"minutes": h, "label": _horizon_label(h), "bias": current_bias, "persistence_pct": None, "n": 0})
        return results

    # Sample M1 indices spaced by sample_every_min (fast — no full recompute per point)
    step = max(1, sample_every_min)
    start_i = 120
    end_i = n - max_h - 1
    if end_i <= start_i:
        for h in horizons:
            results.append({"minutes": h, "label": _horizon_label(h), "bias": current_bias, "persistence_pct": None, "n": 0})
        return results

    span = end_i - start_i
    n_samples = min(max_samples, max(50, span // step))
    sample_indices = np.linspace(start_i, end_i, num=n_samples, dtype=int)

    hits: Dict[int, List[int]] = {h: [] for h in horizons}

    for i in sample_indices:
        t0 = times[i]
        hour = t0.tz_convert(EAT).hour
        if hour < EAT_SESSION_START_HOUR or hour > EAT_SESSION_END_HOUR:
            continue

        bias, _ = _momentum_bias_at_index(work, int(i))
        if bias != current_bias:
            continue

        start_px = closes[i]
        if start_px <= 0:
            continue

        for h in horizons:
            j = min(i + h, n - 1)
            fwd = closes[j] / start_px - 1.0
            if current_bias == "BUY":
                held = fwd > min_move
            else:
                held = fwd < -min_move
            hits[h].append(1 if held else 0)

    for h in horizons:
        arr = hits[h]
        cnt = len(arr)
        pct = round(100.0 * sum(arr) / cnt, 1) if cnt >= 15 else None
        results.append({
            "minutes": h,
            "label": _horizon_label(h),
            "bias": current_bias,
            "persistence_pct": pct,
            "n": cnt,
        })
    return results


def _horizon_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    if minutes % 60 == 0:
        return f"{minutes // 60} hr" if minutes // 60 == 1 else f"{minutes // 60} hrs"
    return f"{minutes} min"


def build_forecast_window(
    m1: pd.DataFrame,
    state: Dict[str, Any],
    horizons: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Primary entry window: now → now + 4h (capped at 20:00 EAT)."""
    window_min = _default_window_min()
    now = now_eat()
    now_ts = pd.Timestamp(now)

    if not m1.empty:
        last_bar = m1.index[-1].tz_convert(EAT)
        # Anchor to latest M1 bar if fresher than clock
        if last_bar > now_ts - pd.Timedelta(minutes=2):
            now_ts = last_bar

    session_end = _session_end_today_eat(now_ts)
    raw_end = now_ts + pd.Timedelta(minutes=window_min)
    end_ts = min(raw_end, session_end)

    if end_ts <= now_ts:
        end_ts = now_ts + pd.Timedelta(minutes=30)

    bias = str(state.get("bias") or "—")
    range_str = _fmt_eat_range(now_ts, end_ts)
    duration_min = int((end_ts - now_ts).total_seconds() / 60)

    # Best supported horizon = longest where persistence >= 50% with enough samples
    best_h = window_min
    for h in reversed(FORECAST_HORIZONS_MIN):
        row = next((x for x in horizons if x["minutes"] == h), None)
        if row and row.get("persistence_pct") is not None and row["n"] >= 20:
            if row["persistence_pct"] >= 50.0:
                best_h = h
                break

    entry_note = ""
    if bias in ("BUY", "SELL"):
        entry_note = (
            f"Enter {bias} any time from {_fmt_eat(now_ts)} until {_fmt_eat(end_ts)} "
            f"({duration_min // 60}h {duration_min % 60}m window). "
            f"Momentum measured on live M1 — enter inside the window."
        )

    return {
        "start_eat": now_ts.isoformat(),
        "end_eat": end_ts.isoformat(),
        "start_display": _fmt_eat(now_ts),
        "end_display": _fmt_eat(end_ts),
        "range_display": range_str,
        "duration_minutes": duration_min,
        "primary_horizon_min": best_h,
        "entry_note": entry_note,
    }


def run_momentum_forecast(m1_bars: List[dict]) -> Dict[str, Any]:
    """
    Full pipeline: M1 → momentum state → horizon persistence → forecast window.
    """
    m1 = bars_list_to_m1_df(m1_bars)
    meta: Dict[str, Any] = {"m1_bars": len(m1)}

    if m1.empty:
        return _empty_forecast(meta, "no M1 bars")

    state = compute_momentum_state(m1)
    meta["momentum"] = state

    if not state.get("ready"):
        return _empty_forecast(meta, f"momentum flat — {state.get('note', '')}")

    bias = str(state["bias"])
    horizons = measure_horizon_persistence(m1, bias)
    window = build_forecast_window(m1, state, horizons)

    # Pick persistence at primary 4h horizon for display confidence
    h4 = next((h for h in horizons if h["minutes"] == DEFAULT_WINDOW_MIN), {})
    conf = (h4.get("persistence_pct") or 0) / 100.0 if h4.get("persistence_pct") else state.get("strength", 0)

    prediction = {
        "ready": True,
        "trained": True,  # compat with existing UI keys
        "bias": bias,
        "strength": state.get("strength"),
        "confidence": round(float(conf), 3),
        "use_for_recommendations": True,
        "rec_source": "momentum_forecast",
        "window": window,
        "horizons": horizons,
        "best_entry_window": window.get("range_display", "—"),
        "entry_note": window.get("entry_note", ""),
        "momentum_note": state.get("note", ""),
        "votes": state.get("votes", {}),
    }

    return {
        "meta": meta,
        "state": state,
        "prediction": prediction,
        "horizons": horizons,
        "window": window,
        "backtest": {
            "horizons": horizons,
            "method": "historical_momentum_persistence",
            "n_m1_bars": len(m1),
        },
    }


def _empty_forecast(meta: Dict[str, Any], reason: str) -> Dict[str, Any]:
    meta["reason"] = reason
    return {
        "meta": meta,
        "state": {"ready": False, "bias": "—", "note": reason},
        "prediction": {
            "ready": False,
            "trained": False,
            "bias": "—",
            "use_for_recommendations": False,
            "reason": reason,
        },
        "horizons": [],
        "window": {},
        "backtest": {},
    }
