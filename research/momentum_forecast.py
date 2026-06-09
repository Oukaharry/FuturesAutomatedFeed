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

from research.eat_time import EAT, eat_hour_from_m1_index, now_eat
from research.market_signals import (
    EAT_SESSION_END_HOUR,
    EAT_SESSION_START_HOUR,
    bars_list_to_m1_df,
    resample_ohlc,
    _ema,
)

# Forecast horizons the user asked for (minutes)
FORECAST_HORIZONS_MIN: Tuple[int, ...] = (10, 20, 60, 180, 240)
MAX_HOLD_MIN = 240  # longest horizon we measure — not a fixed entry window
MIN_MOVE_BPS = 3.0  # 0.03% min move to count as "held direction"
MIN_PERSISTENCE_PCT = 50.0
MIN_PERSISTENCE_SAMPLES = 15
M15_MIN_REGIME_BARS = 2  # 30 min sustained 15m momentum to start a window


def _min_move_pct() -> float:
    try:
        return float(os.environ.get("ML_MOMENTUM_MIN_MOVE_BPS", str(MIN_MOVE_BPS))) / 10000.0
    except ValueError:
        return MIN_MOVE_BPS / 10000.0


def _min_persistence_pct() -> float:
    try:
        return float(os.environ.get("ML_MOMENTUM_MIN_PERSIST_PCT", str(MIN_PERSISTENCE_PCT)))
    except ValueError:
        return MIN_PERSISTENCE_PCT


def _session_end_today_eat(now_local: pd.Timestamp) -> pd.Timestamp:
    """Today 20:00 EAT (last minute of trading window)."""
    d = now_local.date()
    return pd.Timestamp(
        year=d.year, month=d.month, day=d.day,
        hour=EAT_SESSION_END_HOUR, minute=0, tz=EAT,
    )


def _fmt_eat(ts: pd.Timestamp) -> str:
    if ts.tzinfo is None:
        ts = ts.tz_localize(EAT)
    else:
        ts = ts.tz_convert(EAT)
    return ts.strftime("%H:%M EAT")


def _fmt_eat_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
    s = start.tz_convert(EAT) if start.tzinfo else start.tz_localize(EAT)
    e = end.tz_convert(EAT) if end.tzinfo else end.tz_localize(EAT)
    if s.date() == e.date():
        return f"{s.strftime('%H:%M')} – {e.strftime('%H:%M EAT')}"
    return f"{s.strftime('%Y-%m-%d %H:%M')} – {e.strftime('%Y-%m-%d %H:%M EAT')}"


def _min_regime_bars() -> int:
    try:
        return max(1, int(os.environ.get("ML_M15_MIN_REGIME_BARS", str(M15_MIN_REGIME_BARS))))
    except ValueError:
        return M15_MIN_REGIME_BARS


def label_15m_momentum_bars(ohlc_15m: pd.DataFrame) -> pd.Series:
    """
    Causal BUY / SELL / — label on each 15m bar (vectorized, no lookahead).
    Uses EMA9/21 structure + 3-bar return + EMA slope — same logic as _tf_momentum_vote.
    """
    n = len(ohlc_15m)
    if n < 22:
        return pd.Series(["—"] * n, index=ohlc_15m.index, dtype=object)

    c = ohlc_15m["close"].astype(float)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    ema_dir = np.where(ema9 > ema21, 1, -1)
    ret3 = c.pct_change(3)
    ret_dir = np.where(ret3 > 0.0001, 1, np.where(ret3 < -0.0001, -1, 0))
    slope = ema9.pct_change(4)
    slope_dir = np.where(slope > 0, 1, np.where(slope < 0, -1, 0))
    score = ema_dir * 0.5 + ret_dir * 0.35 + slope_dir * 0.15
    labels = np.where(score > 0.15, "BUY", np.where(score < -0.15, "SELL", "—"))
    labels[:21] = "—"
    return pd.Series(labels, index=ohlc_15m.index, dtype=object)


def _window_row(
    bias: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    ohlc_15m: pd.DataFrame,
    *,
    active: bool = False,
) -> Dict[str, Any]:
    """One momentum regime segment on the 15m grid."""
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize(EAT)
    else:
        start_ts = start_ts.tz_convert(EAT)
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize(EAT)
    else:
        end_ts = end_ts.tz_convert(EAT)

    mask = (ohlc_15m.index >= start_ts) & (ohlc_15m.index <= end_ts)
    seg = ohlc_15m.loc[mask]
    start_px = float(seg["close"].iloc[0]) if not seg.empty else 0.0
    end_px = float(seg["close"].iloc[-1]) if not seg.empty else 0.0
    move_pct = round((end_px / start_px - 1.0) * 100, 3) if start_px > 0 else 0.0
    duration_min = max(15, int((end_ts - start_ts).total_seconds() // 60) + 15)

    if active:
        range_display = f"{start_ts.strftime('%H:%M')} – now EAT {bias}"
    else:
        range_display = f"{_fmt_eat_range(start_ts, end_ts)} {bias}"

    return {
        "bias": bias,
        "start_eat": start_ts.isoformat(),
        "end_eat": end_ts.isoformat(),
        "start_display": _fmt_eat(start_ts),
        "end_display": "now" if active else _fmt_eat(end_ts),
        "range_display": range_display,
        "duration_minutes": duration_min,
        "bars": len(seg),
        "move_pct": move_pct,
        "active": active,
    }


def detect_momentum_windows_m15(
    m1: pd.DataFrame,
    *,
    min_bars: Optional[int] = None,
    today_only: bool = True,
) -> Dict[str, Any]:
    """
    Resample M1 → 15m and segment sustained BUY/SELL momentum for the session.

    Example output window: "05:00 – 15:30 EAT BUY" (UTC+3 / EAT).
    """
    empty: Dict[str, Any] = {"windows": [], "active": None, "ohlc_bars": 0, "labels": {}}
    if m1.empty or len(m1) < 60:
        return empty

    ohlc = resample_ohlc(m1, "15min")
    if ohlc.empty or len(ohlc) < 22:
        return empty

    min_seg = min_bars if min_bars is not None else _min_regime_bars()
    now_ts = pd.Timestamp(now_eat())
    today = now_ts.date()

    work = ohlc.copy()
    if today_only:
        keep_idx = []
        for ts in ohlc.index:
            t = ts.tz_convert(EAT) if ts.tzinfo else ts.tz_localize(EAT)
            if t.date() == today:
                keep_idx.append(ts)
        work = ohlc.loc[keep_idx] if keep_idx else ohlc.tail(max(32, min_seg * 4))
    if work.empty:
        work = ohlc.tail(max(32, min_seg * 4))

    # Session filter (02:00–20:00 EAT)
    hours = np.array([eat_hour_from_m1_index(ts) for ts in work.index])
    sess_mask = (hours >= EAT_SESSION_START_HOUR) & (hours <= EAT_SESSION_END_HOUR)
    work = work.iloc[sess_mask]
    if work.empty:
        return empty

    labels = label_15m_momentum_bars(work)
    windows: List[Dict[str, Any]] = []
    i = 0
    n = len(labels)

    while i < n:
        lab = str(labels.iloc[i])
        if lab not in ("BUY", "SELL"):
            i += 1
            continue
        j = i + 1
        while j < n and str(labels.iloc[j]) == lab:
            j += 1
        seg_len = j - i
        is_tail = j >= n
        if seg_len >= min_seg or (is_tail and seg_len >= 1):
            start_ts = work.index[i]
            last_bar = work.index[j - 1]
            is_active = is_tail and str(labels.iloc[-1]) == lab
            if is_active:
                windows.append(_window_row(lab, start_ts, now_ts, work, active=True))
            else:
                end_ts = last_bar + pd.Timedelta(minutes=15)
                windows.append(_window_row(lab, start_ts, end_ts, work, active=False))
        i = j if j > i else i + 1

    active = next((w for w in reversed(windows) if w.get("active")), None)

    return {
        "windows": windows,
        "active": active,
        "ohlc_bars": len(work),
        "labels": {
            "last": str(labels.iloc[-1]) if len(labels) else "—",
            "buy_bars": int((labels == "BUY").sum()),
            "sell_bars": int((labels == "SELL").sum()),
        },
    }


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
        hour = eat_hour_from_m1_index(t0)
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


def _pick_expected_hold(horizons: List[Dict[str, Any]]) -> Tuple[int, Optional[float], str]:
    """
    Longest horizon (10m…4h) where historical persistence meets threshold.
    Not a fixed 4h — driven by M1 backtest on similar momentum.
    """
    min_pct = _min_persistence_pct()
    min_n = MIN_PERSISTENCE_SAMPLES

    qualified = [
        h for h in horizons
        if h.get("persistence_pct") is not None
        and int(h.get("n", 0)) >= min_n
        and float(h["persistence_pct"]) >= min_pct
    ]
    if qualified:
        best = max(qualified, key=lambda x: int(x["minutes"]))
        mins = int(best["minutes"])
        return mins, float(best["persistence_pct"]), _horizon_label(mins)

    any_h = [
        h for h in horizons
        if h.get("persistence_pct") is not None and int(h.get("n", 0)) >= min_n
    ]
    if any_h:
        best = max(any_h, key=lambda x: (float(x["persistence_pct"]), int(x["minutes"])))
        mins = int(best["minutes"])
        return mins, float(best["persistence_pct"]), _horizon_label(mins)

    return 20, None, "20 min"


def build_forecast_window(
    m1: pd.DataFrame,
    state: Dict[str, Any],
    horizons: List[Dict[str, Any]],
    *,
    m15_regimes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Forecast = active 15m momentum regime (e.g. 05:00 – now EAT BUY) plus expected hold.
    """
    now_ts = pd.Timestamp(now_eat())

    last_bar_eat = None
    if not m1.empty:
        last_bar = m1.index[-1]
        last_bar_eat = last_bar.tz_convert(EAT) if last_bar.tzinfo else last_bar.tz_localize(EAT)

    bias = str(state.get("bias") or "—")
    hold_min, hold_pct, hold_label = _pick_expected_hold(horizons)

    session_end = _session_end_today_eat(now_ts)
    valid_through = min(now_ts + pd.Timedelta(minutes=hold_min), session_end)

    now_display = _fmt_eat(now_ts)
    regimes = m15_regimes or detect_momentum_windows_m15(m1)
    active = regimes.get("active")
    windows_today = regimes.get("windows") or []

    if active and active.get("bias") in ("BUY", "SELL"):
        bias = str(active["bias"])
        regime_start = active.get("start_display") or "—"
        range_display = active.get("range_display") or f"{regime_start} – now EAT {bias}"
        hold_display = range_display
        move_pct = active.get("move_pct")
        move_bit = f" Move since regime start: {move_pct:+.2f}%." if move_pct is not None else ""
        pct_bit = f" Similar {bias} regimes held ~{hold_label} in {hold_pct:.0f}% of past cases." if hold_pct else ""
        entry_note = (
            f"{bias} momentum on 15m bars since {regime_start} — still active at {now_display}.{move_bit}"
            f"{pct_bit} M1 resampled to 15m (UTC+3 / EAT)."
        )
        window_start = active.get("start_eat") or now_ts.isoformat()
    elif bias in ("BUY", "SELL"):
        range_display = f"{bias} at {now_display} (no 30m+ 15m regime yet)"
        hold_display = f"~{hold_label}"
        if hold_pct is not None:
            hold_display += f" ({hold_pct:.0f}% held on M1 history)"
        pct_bit = f" Similar momentum held {hold_label} in {hold_pct:.0f}% of cases." if hold_pct else ""
        entry_note = (
            f"{bias} signal at {now_display} — waiting for 30m sustained 15m momentum.{pct_bit}"
        )
        window_start = now_ts.isoformat()
    else:
        range_display = "—"
        hold_display = "—"
        entry_note = "No clear 15m momentum regime in session yet."
        window_start = now_ts.isoformat()

    return {
        "start_eat": window_start,
        "valid_through_eat": valid_through.isoformat(),
        "now_eat_display": now_display,
        "valid_through_display": _fmt_eat(valid_through),
        "expected_hold_minutes": hold_min,
        "expected_hold_label": hold_label,
        "expected_hold_pct": hold_pct,
        "hold_display": hold_display,
        "range_display": range_display,
        "best_entry_window": range_display,
        "primary_horizon_min": hold_min,
        "entry_note": entry_note,
        "bias_now": bias,
        "last_bar_eat": _fmt_eat(last_bar_eat) if last_bar_eat is not None else None,
        "duration_minutes": active.get("duration_minutes") if active else hold_min,
        "active_regime": active,
        "windows_today": windows_today,
        "m15_regime_bars": regimes.get("ohlc_bars", 0),
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
    m15_regimes = detect_momentum_windows_m15(m1)
    meta["momentum"] = state
    meta["m15_regimes"] = m15_regimes

    active_regime = m15_regimes.get("active")
    if active_regime and active_regime.get("bias") in ("BUY", "SELL"):
        state = dict(state)
        state["bias"] = active_regime["bias"]
        state["ready"] = True
        state["regime_note"] = active_regime.get("range_display")

    if not state.get("ready"):
        if m15_regimes.get("windows"):
            last_w = m15_regimes["windows"][-1]
            return _empty_forecast(
                meta,
                f"last 15m regime ended — {last_w.get('range_display', '')}",
                partial_regimes=m15_regimes,
            )
        return _empty_forecast(meta, f"momentum flat — {state.get('note', '')}")

    bias = str(state["bias"])
    horizons = measure_horizon_persistence(m1, bias)
    window = build_forecast_window(m1, state, horizons, m15_regimes=m15_regimes)

    # Confidence from persistence at the chosen hold horizon (not fixed 4h)
    h_row = next((h for h in horizons if h["minutes"] == window.get("expected_hold_minutes")), {})
    conf_pct = h_row.get("persistence_pct") or window.get("expected_hold_pct")
    conf = (conf_pct or 0) / 100.0 if conf_pct else state.get("strength", 0)

    last_close = float(m1["close"].iloc[-1]) if not m1.empty else None

    prediction = {
        "ready": True,
        "trained": True,  # compat with existing UI keys
        "bias": bias,
        "bias_now": bias,
        "now_eat": window.get("now_eat_display"),
        "expected_hold": window.get("hold_display"),
        "expected_hold_minutes": window.get("expected_hold_minutes"),
        "momentum_window": window.get("range_display"),
        "windows_today": window.get("windows_today") or [],
        "active_regime": window.get("active_regime"),
        "strength": state.get("strength"),
        "confidence": round(float(conf), 3),
        "use_for_recommendations": True,
        "rec_source": "momentum_forecast",
        "window": window,
        "horizons": horizons,
        "best_entry_window": window.get("range_display") or window.get("hold_display", "—"),
        "entry_note": window.get("entry_note", ""),
        "momentum_note": state.get("regime_note") or state.get("note", ""),
        "votes": state.get("votes", {}),
        "entry_price": last_close,
        "last_bar_eat": window.get("last_bar_eat"),
    }

    return {
        "meta": meta,
        "state": state,
        "prediction": prediction,
        "horizons": horizons,
        "window": window,
        "m15_regimes": m15_regimes,
        "backtest": {
            "horizons": horizons,
            "method": "m15_momentum_regimes",
            "n_m1_bars": len(m1),
            "windows_today": m15_regimes.get("windows") or [],
        },
    }


def _empty_forecast(
    meta: Dict[str, Any],
    reason: str,
    *,
    partial_regimes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta["reason"] = reason
    regimes = partial_regimes or {}
    windows = regimes.get("windows") or []
    return {
        "meta": meta,
        "state": {"ready": False, "bias": "—", "note": reason},
        "prediction": {
            "ready": False,
            "trained": False,
            "bias": "—",
            "use_for_recommendations": False,
            "reason": reason,
            "windows_today": windows,
        },
        "horizons": [],
        "window": {"windows_today": windows},
        "m15_regimes": regimes,
        "backtest": {"windows_today": windows},
    }
