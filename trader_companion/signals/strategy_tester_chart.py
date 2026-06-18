"""Chart replay data for the Strategy Tester window.

Builds M1 candles + tick mid-price paths around simulated trade entries
using the same MT5 tick walk as trade_simulator (bid/ask fill rules).
Simulates the companion's indicator set bar-by-bar for MT5-style overlays.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from trader_companion.signals import trade_simulator as sim
except ImportError:
    try:
        import trade_simulator as sim  # type: ignore
    except ImportError:
        sim = None

PRE_ENTRY_MIN = 25
POST_EXIT_MIN = 20
MAX_TICKS_CHART = 120_000

# Matches TradeOpssAIApp._get_indicator_map names (offline M1 replay).
INDICATOR_NAMES = (
    "RSI", "MACD", "Stochastic", "CCI", "Supertrend", "Momentum",
    "BollingerBands", "SMA", "EMA", "DMI", "MFI", "ROC", "ParabolicSAR",
    "TSI", "WilliamsR", "Donchian", "PriceChannel", "Keltner", "Vortex",
    "CMO", "Coppock", "UltimateOsc", "ElderRay", "Gator", "Fractal",
)


def _mid_tick(tick) -> float:
    bid = float(tick["bid"])
    ask = float(tick["ask"])
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return bid or ask or 0.0


def fetch_m1_range(symbol: str, from_ts: int, to_ts: int):
    if sim is None or not sim.MT5_AVAILABLE:
        return None
    sym = sim._resolve_symbol(symbol)
    if not sym or to_ts <= from_ts:
        return None
    try:
        import MetaTrader5 as mt5
        if to_ts - from_ts > 3 * 86400:
            return sim.fetch_rates_range_chunked(sym, mt5.TIMEFRAME_M1, from_ts, to_ts)
        return sim.fetch_rates_range(sym, mt5.TIMEFRAME_M1, from_ts, to_ts)
    except Exception:
        return None


def _rates_to_candles(rates) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if rates is None:
        return out
    for r in rates:
        out.append({
            "ts": int(r[0]),
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
            "vol": float(r[5]) if len(r) > 5 else 0.0,
        })
    return out


def _tick_series(ticks, max_points: int = MAX_TICKS_CHART) -> List[Dict[str, Any]]:
    if ticks is None or len(ticks) == 0:
        return []
    ordered = sorted(ticks, key=sim._tick_sort_key)
    step = max(1, len(ordered) // max_points)
    series: List[Dict[str, Any]] = []
    for i, tick in enumerate(ordered):
        if i % step and i != len(ordered) - 1:
            continue
        t = int(tick["time"])
        bid = float(tick["bid"])
        ask = float(tick["ask"])
        mid = _mid_tick(tick)
        if mid <= 0:
            continue
        series.append({"ts": t, "bid": bid, "ask": ask, "mid": mid})
    return series


def align_ticks_to_candles(tick_series: List[Dict[str, Any]],
                           candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only ticks that fall inside the M1 chart window."""
    if not candles:
        return list(tick_series or [])
    lo = int(candles[0]["ts"])
    hi = int(candles[-1]["ts"]) + 60
    return [
        t for t in (tick_series or [])
        if lo <= int(t["ts"]) <= hi and float(t.get("mid") or 0) > 0
    ]


def _nearest_candle_ref(candles: List[Dict[str, Any]], ts: int) -> float:
    if not candles:
        return 0.0
    best = candles[0]
    best_d = abs(int(best["ts"]) - ts)
    for c in candles:
        d = abs(int(c["ts"]) - ts)
        if d < best_d:
            best, best_d = c, d
    return float(best["c"])


def sanitize_tick_series(tick_series: List[Dict[str, Any]],
                         candles: List[Dict[str, Any]],
                         entry_price: float,
                         from_ts: int, to_ts: int) -> List[Dict[str, Any]]:
    """Drop ticks outside the chart window or far from nearby M1 (bad MT5 rows)."""
    if not tick_series:
        return []
    lo, hi = int(from_ts), int(to_ts)
    kept: List[Dict[str, Any]] = []
    for t in tick_series:
        ts = int(t["ts"])
        if ts < lo or ts > hi:
            continue
        mid = float(t.get("mid") or 0)
        if mid <= 0:
            continue
        ref = _nearest_candle_ref(candles, ts) or float(entry_price or 0)
        if ref > 0 and abs(mid - ref) > 200:
            continue
        kept.append(t)
    return kept


def build_replay_timeline(candles: List[Dict[str, Any]],
                          tick_series: List[Dict[str, Any]],
                          steps_per_bar: int = 16) -> List[Dict[str, Any]]:
    """Scrubber/play frames locked to M1 bars — candles always form on screen."""
    if not candles:
        return []
    clipped = align_ticks_to_candles(tick_series, candles)
    frames: List[Dict[str, Any]] = []
    n_bars = len(candles)
    for bar_i, c in enumerate(candles):
        bar_ts = int(c["ts"])
        bar_end = bar_ts + 60
        bar_ticks = [t for t in clipped if bar_ts <= int(t["ts"]) < bar_end]
        n_steps = steps_per_bar
        if bar_ticks:
            picks = list(range(len(bar_ticks)))
            if len(picks) > n_steps:
                step = max(1, len(picks) // n_steps)
                picks = list(range(0, len(picks), step))
                if picks[-1] != len(bar_ticks) - 1:
                    picks.append(len(bar_ticks) - 1)
            for j, tick_idx in enumerate(picks):
                frac = (j + 1) / len(picks)
                t = bar_ticks[tick_idx]
                frames.append({
                    "ts": int(t["ts"]),
                    "mid": float(t["mid"]),
                    "bid": float(t.get("bid") or t["mid"]),
                    "ask": float(t.get("ask") or t["mid"]),
                    "bar_i": bar_i,
                    "frac": min(1.0, frac),
                    "bar_n": n_bars,
                })
        else:
            o, cl = float(c["o"]), float(c["c"])
            for step in range(1, n_steps + 1):
                frac = step / n_steps
                ts = min(bar_end - 1, bar_ts + int(60 * frac))
                px = o + (cl - o) * frac
                frames.append({
                    "ts": ts, "mid": px,
                    "bid": px, "ask": px,
                    "bar_i": bar_i,
                    "frac": frac,
                    "bar_n": n_bars,
                    "_synthetic": True,
                })
    return frames


def candles_at_frame(candles: List[Dict[str, Any]], bar_i: int,
                     frac: float) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (completed bars, forming bar) for a replay frame — no timestamp guessing."""
    if not candles or bar_i < 0:
        return [], None
    bar_i = min(bar_i, len(candles) - 1)
    frac = max(0.0, min(1.0, float(frac)))
    c = candles[bar_i]
    o, cl = float(c["o"]), float(c["c"])
    h, l = float(c["h"]), float(c["l"])
    if frac >= 1.0:
        return candles[: bar_i + 1], None
    completed = candles[:bar_i]
    close = o + (cl - o) * frac
    hi = max(o, close, o + max(0.0, h - o) * frac)
    lo = min(o, close, o - max(0.0, o - l) * frac)
    forming = {
        "ts": int(c["ts"]), "o": o, "h": hi, "l": lo, "c": close,
        "vol": c.get("vol", 0), "forming": True,
    }
    return completed, forming


def replay_x_for_bars(candles: List[Dict[str, Any]], bar_i: int,
                      from_ts: int, to_ts: int,
                      max_visible_bars: int = 32) -> Tuple[int, int]:
    """X-axis for replay — grows from bar 0, then scrolls (keeps painted bars on screen)."""
    if not candles:
        return from_ts, to_ts
    bar_i = max(0, min(bar_i, len(candles) - 1))
    if bar_i <= max_visible_bars:
        i0 = 0
    else:
        i0 = bar_i - max_visible_bars
    i1 = min(len(candles) - 1, bar_i + 1)
    t0 = int(candles[i0]["ts"])
    t1 = int(candles[i1]["ts"]) + 90
    pad = max(30, int((t1 - t0) * 0.04))
    return max(from_ts, t0 - pad), min(to_ts, t1 + pad)


def chart_price_bounds(candles: List[Dict[str, Any]],
                       ctx: Dict[str, Any]) -> Tuple[float, float]:
    """Stable Y scale from full M1 window + trade levels (not tick outliers)."""
    prices: List[float] = []
    for c in candles:
        prices.extend([float(c["h"]), float(c["l"])])
    for key in ("entry_price", "exit_price", "tp_level", "sl_level"):
        v = ctx.get(key)
        if v is not None:
            prices.append(float(v))
    for tr in ctx.get("trades") or []:
        for key in ("entry_price", "exit_price", "tp_level", "sl_level"):
            v = tr.get(key)
            if v is not None:
                prices.append(float(v))
    if not prices:
        return 0.0, 1.0
    p_min, p_max = min(prices), max(prices)
    pad = max(5.0, (p_max - p_min) * 0.10)
    return p_min - pad, p_max + pad


def replay_x_bounds(from_ts: int, to_ts: int, cursor_ts: Optional[int],
                    draw_candles: List[Dict]) -> Tuple[int, int]:
    """Zoom X axis to visible replay window so candles are readable."""
    if not cursor_ts or not draw_candles:
        return from_ts, to_ts
    vis_lo = max(from_ts, int(draw_candles[0]["ts"]) - 120)
    vis_hi = min(to_ts, int(cursor_ts) + 240)
    if vis_hi - vis_lo < 300:
        vis_hi = min(to_ts, vis_lo + 300)
    return vis_lo, max(vis_hi, vis_lo + 60)


def _ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if not closes or period < 1:
        return out
    k = 2.0 / (period + 1.0)
    ema = closes[0]
    for i, c in enumerate(closes):
        ema = c * k + ema * (1.0 - k)
        if i >= period - 1:
            out[i] = ema
    return out


def _sma_series(closes: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return out
    for i in range(period - 1, len(closes)):
        out[i] = sum(closes[i - period + 1:i + 1]) / period
    return out


def _rsi_series(closes: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
        if i < period:
            continue
        avg_g = sum(gains[-period:]) / period
        avg_l = sum(losses[-period:]) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _macd_hist(closes: List[float]) -> List[Optional[float]]:
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if ema12[i] is not None and ema26[i] is not None:
            out[i] = ema12[i] - ema26[i]
    return out


def _roc_series(closes: List[float], period: int = 10) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(period, len(closes)):
        base = closes[i - period]
        if base:
            out[i] = (closes[i] - base) / base * 100.0
    return out


def _cci_series(highs, lows, closes, period: int = 20) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        tp = [(highs[j] + lows[j] + closes[j]) / 3.0 for j in range(i - period + 1, i + 1)]
        mean = sum(tp) / period
        md = sum(abs(x - mean) for x in tp) / period
        if md:
            out[i] = (tp[-1] - mean) / (0.015 * md)
    return out


def _stoch_k(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        hh = max(highs[i - period + 1:i + 1])
        ll = min(lows[i - period + 1:i + 1])
        if hh > ll:
            out[i] = (closes[i] - ll) / (hh - ll) * 100.0
    return out


def _bbands(closes, period: int = 20):
    mid = _sma_series(closes, period)
    upper, lower = [None] * len(closes), [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        m = mid[i]
        if m is None:
            continue
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i] = m + 2 * sd
        lower[i] = m - 2 * sd
    return mid, upper, lower


def _donchian(highs, lows, period: int = 20):
    up, lo = [None] * len(highs), [None] * len(highs)
    for i in range(period - 1, len(highs)):
        up[i] = max(highs[i - period + 1:i + 1])
        lo[i] = min(lows[i - period + 1:i + 1])
    return up, lo


def _sig_from_cmp(val, buy_cond, sell_cond) -> Optional[str]:
    if buy_cond:
        return "buy"
    if sell_cond:
        return "sell"
    return None


def compute_chart_overlays_light(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fast overlays for long period charts (EMA + volume only)."""
    if not candles:
        return {"ema21": [], "bar_signals": [], "indicators": {}, "volumes": []}
    closes = [float(c["c"]) for c in candles]
    return {
        "ema21": _ema_series(closes, 21),
        "bar_signals": [],
        "indicators": {name: [] for name in INDICATOR_NAMES},
        "volumes": [c.get("vol", 0) for c in candles],
    }


def compute_chart_overlays(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bar-by-bar indicator simulation (same names as live voter)."""
    n = len(candles)
    if n < 2:
        return {"ema21": [], "bar_signals": [], "indicators": {}, "volumes": []}

    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    ema21 = _ema_series(closes, 21)
    ema50 = _ema_series(closes, 50)
    sma20 = _sma_series(closes, 20)
    sma50 = _sma_series(closes, 50)
    rsi = _rsi_series(closes, 14)
    macd_h = _macd_hist(closes)
    roc = _roc_series(closes, 10)
    cci = _cci_series(highs, lows, closes, 20)
    stoch = _stoch_k(highs, lows, closes, 14)
    bb_mid, bb_up, bb_lo = _bbands(closes, 20)
    dch_up, dch_lo = _donchian(highs, lows, 20)

    indicators: Dict[str, List[Optional[str]]] = {name: [] for name in INDICATOR_NAMES}
    bar_signals: List[Optional[str]] = []

    for i in range(n):
        states: Dict[str, Optional[str]] = {}
        c, h, l = closes[i], highs[i], lows[i]

        if ema21[i] is not None:
            states["EMA"] = _sig_from_cmp(c, c > ema21[i], c < ema21[i])
        if sma50[i] is not None:
            states["SMA"] = _sig_from_cmp(c, c > sma50[i], c < sma50[i])
        if rsi[i] is not None:
            states["RSI"] = _sig_from_cmp(
                rsi[i], rsi[i] < 35, rsi[i] > 65)
            if states["RSI"] is None:
                states["RSI"] = "buy" if rsi[i] > 50 else "sell"
        if macd_h[i] is not None:
            states["MACD"] = _sig_from_cmp(macd_h[i], macd_h[i] > 0, macd_h[i] < 0)
        if roc[i] is not None:
            states["Momentum"] = states["ROC"] = _sig_from_cmp(
                roc[i], roc[i] > 0, roc[i] < 0)
        if cci[i] is not None:
            states["CCI"] = _sig_from_cmp(cci[i], cci[i] < -100, cci[i] > 100)
        if stoch[i] is not None:
            states["Stochastic"] = _sig_from_cmp(
                stoch[i], stoch[i] < 25, stoch[i] > 75)
        if bb_lo[i] is not None and bb_up[i] is not None:
            states["BollingerBands"] = _sig_from_cmp(
                c, c <= bb_lo[i], c >= bb_up[i])
        if dch_up[i] is not None:
            states["Donchian"] = states["PriceChannel"] = _sig_from_cmp(
                c, c >= dch_up[i], c <= dch_lo[i])
        if ema21[i] is not None and ema50[i] is not None:
            states["Supertrend"] = _sig_from_cmp(
                None, ema21[i] > ema50[i] and c > ema50[i],
                ema21[i] < ema50[i] and c < ema50[i])
            states["DMI"] = _sig_from_cmp(
                None, ema21[i] > ema50[i], ema21[i] < ema50[i])
        if sma20[i] is not None:
            states["Keltner"] = _sig_from_cmp(c, c > sma20[i], c < sma20[i])
        if i >= 2:
            states["Fractal"] = _sig_from_cmp(
                None, l <= min(lows[i - 2:i]), h >= max(highs[i - 2:i]))
        if i >= 5:
            mom = c - closes[i - 5]
            states["CMO"] = states["TSI"] = states["UltimateOsc"] = _sig_from_cmp(
                mom, mom > 0, mom < 0)
            states["WilliamsR"] = states["MFI"] = states["Vortex"] = states["Coppock"] = (
                states["CMO"])
            states["ElderRay"] = _sig_from_cmp(
                None, h - ema21[i] > ema21[i] - l if ema21[i] else False,
                ema21[i] - l > h - ema21[i] if ema21[i] else False)
            st_sig = states.get("Supertrend")
            if st_sig is not None:
                states["Gator"] = states["ParabolicSAR"] = st_sig

        for name in INDICATOR_NAMES:
            indicators[name].append(states.get(name))

        buys = sum(1 for s in states.values() if s == "buy")
        sells = sum(1 for s in states.values() if s == "sell")
        if buys > sells:
            bar_signals.append("buy")
        elif sells > buys:
            bar_signals.append("sell")
        else:
            bar_signals.append(None)

    return {
        "ema21": ema21,
        "bar_signals": bar_signals,
        "indicators": indicators,
        "volumes": [c.get("vol", 0) for c in candles],
    }


def bar_index_for_ts(candles: List[Dict], ts: int) -> int:
    if not candles or not ts:
        return 0
    bi, _ = bar_frac_for_ts(candles, ts)
    return bi


def bar_frac_for_ts(candles: List[Dict], ts: int) -> Tuple[int, float]:
    """M1 bar index + fraction [0,1] within the bar for an epoch timestamp."""
    if not candles or not ts:
        return 0, 0.0
    ts = int(ts)
    first = int(candles[0]["ts"])
    if ts <= first:
        return 0, 0.0
    for i, c in enumerate(candles):
        bts = int(c["ts"])
        if bts <= ts < bts + 60:
            return i, min(1.0, max(0.0, (ts - bts) / 60.0))
    return len(candles) - 1, 1.0


def _candles_cover_ts(candles: List[Dict], ts: int, pad_sec: int = 60) -> bool:
    if not candles or not ts:
        return False
    return int(candles[-1]["ts"]) + pad_sec >= int(ts)


def x_slot_for_bar(bar_i: int, n_bars: int, ml: float, pw: float) -> float:
    """Pixel X for bar index — no timestamp math (always on-screen)."""
    n = max(1, int(n_bars))
    slot = pw / n
    return ml + slot * bar_i + slot * 0.5


def build_trade_replay(trade_row: Dict[str, Any],
                       symbol: Optional[str] = None,
                       pre_min: int = PRE_ENTRY_MIN,
                       post_min: int = POST_EXIT_MIN) -> Dict[str, Any]:
    """Assemble candles + ticks + levels + indicator overlays for one trade."""
    sym = symbol or trade_row.get("symbol") or "ustech"
    entry_ts = int(trade_row.get("entry_time") or trade_row.get("entry_ts") or 0)
    entry_price = float(trade_row.get("entry_price") or 0)
    direction = str(trade_row.get("side") or trade_row.get("direction") or "").lower()
    tp_level = trade_row.get("tp_level")
    sl_level = trade_row.get("sl_level")
    tp_pts = float(trade_row.get("tp_points") or 0)
    sl_pts = float(trade_row.get("sl_points") or 0)

    if not entry_ts:
        return {"error": "no entry time on trade row"}

    if tp_level is None and entry_price and tp_pts:
        sign = 1.0 if direction == "buy" else -1.0
        tp_level = round(entry_price + sign * tp_pts, 2)
    if sl_level is None and entry_price and sl_pts:
        sign = 1.0 if direction == "buy" else -1.0
        sl_level = round(entry_price - sign * sl_pts, 2)

    now_ts = sim._mt5_now_ts() if sim else 0
    max_walk_sec = sim.MAX_WALK_MIN * 60 if sim else 3600
    row_exit = int(trade_row.get("exit_time") or 0)
    if not row_exit or str(trade_row.get("outcome", "")).lower() == "open":
        row_exit = now_ts or (entry_ts + max_walk_sec)

    from_ts = entry_ts - pre_min * 60
    # Chart must span the full open trade — not just entry + a few bars
    trade_span = max(60, row_exit - entry_ts) if row_exit > entry_ts else max_walk_sec
    to_ts = entry_ts + trade_span + post_min * 60
    if row_exit:
        to_ts = max(to_ts, row_exit + post_min * 60)
    if now_ts:
        to_ts = min(to_ts, now_ts + 60)

    if sim:
        sim.ensure_mt5()

    def _load_chart_window(f_ts: int, t_ts: int):
        m1 = fetch_m1_range(sym, f_ts, t_ts)
        cndl = _rates_to_candles(m1)
        t_raw = sim.fetch_ticks(sym, f_ts, t_ts) if sim else None
        t_ser = _tick_series(t_raw)
        t_ser = sanitize_tick_series(t_ser, cndl, entry_price, f_ts, t_ts)
        t_ser = align_ticks_to_candles(t_ser, cndl)
        return m1, cndl, t_raw, t_ser

    m1_rates, candles, ticks, tick_series = _load_chart_window(from_ts, to_ts)

    fill_ts, fill_px = entry_ts, entry_price
    if sim and ticks is not None and len(ticks) and direction in ("buy", "sell"):
        fill_ts, fill_px = sim.entry_fill_from_ticks(
            ticks, entry_ts, direction, entry_price)

    walk: Dict[str, Any] = {}
    if sim and direction in ("buy", "sell") and tp_pts and sl_pts:
        walk = sim.walk_tp_sl(
            fill_ts, fill_px, direction, tp_pts, sl_pts,
            m1_rates, ticks=ticks, symbol=sym)

    final_exit_ts = int(trade_row.get("exit_time") or walk.get("exit_ts") or 0)
    need_to_ts = max(
        to_ts,
        (final_exit_ts + post_min * 60) if final_exit_ts else to_ts,
        fill_ts + max_walk_sec,
    )
    if now_ts:
        need_to_ts = min(need_to_ts, now_ts + 60)
    if need_to_ts > to_ts or not _candles_cover_ts(candles, final_exit_ts or fill_ts):
        to_ts = need_to_ts
        m1_rates, candles, ticks, tick_series = _load_chart_window(from_ts, to_ts)

    overlay = compute_chart_overlays(candles)
    replay_frames = build_replay_timeline(candles, tick_series)

    entry_bar, entry_frac = bar_frac_for_ts(candles, fill_ts)
    if final_exit_ts:
        exit_bar, exit_frac = bar_frac_for_ts(candles, final_exit_ts)
    else:
        exit_bar, exit_frac = max(0, len(candles) - 1), 1.0
    if exit_bar < entry_bar or (exit_bar == entry_bar and exit_frac <= entry_frac):
        exit_frac = min(1.0, entry_frac + 0.05)

    return {
        "symbol": sym,
        "direction": direction,
        "entry_ts": fill_ts,
        "entry_price": fill_px,
        "exit_ts": trade_row.get("exit_time") or walk.get("exit_ts"),
        "exit_price": trade_row.get("exit_price") or walk.get("exit_price"),
        "tp_level": tp_level,
        "sl_level": sl_level,
        "outcome": trade_row.get("outcome"),
        "candles": candles,
        "ticks": tick_series,
        "replay_frames": replay_frames,
        "overlay": overlay,
        "walk": walk,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "tick_count": len(ticks) if ticks is not None else 0,
        "frame_count": len(replay_frames),
        "walk_mode": walk.get("walk_mode") or ("ticks" if tick_series else "m1"),
        "trade_id": trade_row.get("trade_id"),
        "acct_num": trade_row.get("acct_num"),
        "phase_key": trade_row.get("phase_key"),
        "batch": trade_row.get("batch"),
        "entry_bar": entry_bar,
        "entry_frac": round(entry_frac, 4),
        "exit_bar": exit_bar,
        "exit_frac": round(exit_frac, 4),
    }


def frame_reached(cur_bar: int, cur_frac: float,
                  target_bar: int, target_frac: float) -> bool:
    cur_bar, target_bar = int(cur_bar), int(target_bar)
    cur_frac, target_frac = float(cur_frac), float(target_frac)
    return (cur_bar > target_bar
            or (cur_bar == target_bar and cur_frac >= target_frac))


def visible_bar_window(cur_bar: int, n_candles: int,
                       max_visible: int = 96) -> Tuple[int, int, int]:
    """(first_bar_index, cur_bar, n_slots) for a scrolling replay viewport."""
    n_candles = max(1, int(n_candles))
    cur_bar = max(0, min(int(cur_bar), n_candles - 1))
    max_visible = max(24, int(max_visible))
    if cur_bar + 1 <= max_visible:
        return 0, cur_bar, cur_bar + 1
    i0 = cur_bar - max_visible + 1
    return i0, cur_bar, max_visible


def adaptive_steps_per_bar(n_bars: int, target_frames: int = 30000) -> int:
    n_bars = max(1, int(n_bars))
    return max(1, min(16, target_frames // n_bars))


def annotate_trade_row(row: Dict[str, Any],
                       candles: List[Dict[str, Any]],
                       ticks=None) -> Optional[Dict[str, Any]]:
    """Marker dict for one simulated trade on a shared period chart."""
    entry_ts = int(row.get("entry_time") or row.get("entry_ts") or 0)
    if not entry_ts or not candles:
        return None
    entry_price = float(row.get("entry_price") or 0)
    direction = str(row.get("side") or row.get("direction") or "").lower()
    tp_level = row.get("tp_level")
    sl_level = row.get("sl_level")
    tp_pts = float(row.get("tp_points") or 0)
    sl_pts = float(row.get("sl_points") or 0)
    if tp_level is None and entry_price and tp_pts:
        sign = 1.0 if direction == "buy" else -1.0
        tp_level = round(entry_price + sign * tp_pts, 2)
    if sl_level is None and entry_price and sl_pts:
        sign = 1.0 if direction == "buy" else -1.0
        sl_level = round(entry_price - sign * sl_pts, 2)

    fill_ts, fill_px = entry_ts, entry_price
    if sim and ticks is not None and len(ticks) and direction in ("buy", "sell"):
        fill_ts, fill_px = sim.entry_fill_from_ticks(
            ticks, entry_ts, direction, entry_price)

    final_exit_ts = int(row.get("exit_time") or 0)
    entry_bar, entry_frac = bar_frac_for_ts(candles, fill_ts)
    if final_exit_ts:
        exit_bar, exit_frac = bar_frac_for_ts(candles, final_exit_ts)
    else:
        exit_bar, exit_frac = entry_bar, 1.0
    if exit_bar < entry_bar or (exit_bar == entry_bar and exit_frac <= entry_frac):
        exit_frac = min(1.0, entry_frac + 0.05)

    return {
        "trade_id": row.get("trade_id"),
        "batch": row.get("batch"),
        "acct_num": row.get("acct_num"),
        "phase_key": row.get("phase_key"),
        "direction": direction,
        "entry_ts": fill_ts,
        "entry_price": fill_px,
        "exit_ts": final_exit_ts or None,
        "exit_price": row.get("exit_price"),
        "tp_level": tp_level,
        "sl_level": sl_level,
        "outcome": row.get("outcome"),
        "entry_bar": entry_bar,
        "entry_frac": round(entry_frac, 4),
        "exit_bar": exit_bar,
        "exit_frac": round(exit_frac, 4),
    }


def active_trade_at_frame(trades: List[Dict[str, Any]], cur_bar: int,
                          cur_frac: float) -> Optional[Dict[str, Any]]:
    """Most recent trade that has opened but not yet closed at this frame."""
    active = None
    for tr in trades:
        if not frame_reached(cur_bar, cur_frac,
                             int(tr.get("entry_bar") or 0),
                             float(tr.get("entry_frac") or 0)):
            continue
        if tr.get("exit_ts") and frame_reached(
                cur_bar, cur_frac,
                int(tr.get("exit_bar") or 0),
                float(tr.get("exit_frac") or 1.0)):
            continue
        active = tr
    return active


def frame_index_for_bar(frames: List[Dict[str, Any]], bar_i: int,
                        frac: float = 0.0) -> int:
    if not frames:
        return 0
    bar_i, frac = int(bar_i), float(frac)
    for i, fr in enumerate(frames):
        bi = int(fr.get("bar_i") or 0)
        bf = float(fr.get("frac") or 0)
        if bi > bar_i or (bi == bar_i and bf >= frac):
            return i
    return len(frames) - 1


def build_bar_frames(candles: List[Dict[str, Any]],
                     steps_per_bar: int = 8) -> List[Dict[str, Any]]:
    """Replay steps per M1 bar — forming candle animates like MT5 (frac 0→1)."""
    frames: List[Dict[str, Any]] = []
    n = len(candles)
    steps = max(1, int(steps_per_bar))
    for i, c in enumerate(candles):
        o, cl = float(c["o"]), float(c["c"])
        bar_ts = int(c["ts"])
        for step in range(1, steps + 1):
            frac = step / steps
            mid = o + (cl - o) * frac
            ts = min(bar_ts + 59, bar_ts + int(60 * frac))
            frames.append({
                "ts": ts,
                "mid": mid,
                "bid": mid,
                "ask": mid,
                "bar_i": i,
                "frac": frac,
                "bar_n": n,
            })
    return frames


def build_period_chart(trade_rows: List[Dict[str, Any]],
                       symbol: Optional[str] = None) -> Dict[str, Any]:
    """Static period chart — all M1 candles + all trade levels (matplotlib-style)."""
    rows = sorted(
        [r for r in (trade_rows or []) if int(r.get("entry_time") or r.get("entry_ts") or 0)],
        key=lambda r: int(r.get("entry_time") or r.get("entry_ts") or 0),
    )
    if not rows:
        return {"error": "no trades to chart"}

    sym = symbol or rows[0].get("symbol") or "ustech"
    now_ts = sim._mt5_now_ts() if sim else 0
    max_walk_sec = sim.MAX_WALK_MIN * 60 if sim else 3600

    first_entry = int(rows[0].get("entry_time") or rows[0].get("entry_ts"))
    last_exit = first_entry
    for r in rows:
        et = int(r.get("entry_time") or r.get("entry_ts") or 0)
        xt = int(r.get("exit_time") or 0)
        last_exit = max(last_exit, xt or (et + max_walk_sec))

    from_ts = first_entry - PRE_ENTRY_MIN * 60
    to_ts = last_exit + POST_EXIT_MIN * 60
    if now_ts:
        to_ts = min(int(to_ts), now_ts + 60)

    if sim:
        sim.ensure_mt5()

    m1 = fetch_m1_range(sym, int(from_ts), int(to_ts))
    candles = _rates_to_candles(m1)
    if not candles:
        return {"error": "no M1 data for period — connect MT5"}

    overlay = compute_chart_overlays_light(candles)
    trades: List[Dict[str, Any]] = []
    for row in rows:
        ann = annotate_trade_row(row, candles, ticks=None)
        if ann:
            trades.append(ann)

    if not trades:
        return {"error": "could not place trades on chart"}

    bar_frames = build_bar_frames(candles)

    return {
        "period_mode": True,
        "static_mode": True,
        "symbol": sym,
        "trades": trades,
        "n_trades": len(trades),
        "candles": candles,
        "ticks": [],
        "replay_frames": bar_frames,
        "overlay": overlay,
        "from_ts": int(from_ts),
        "to_ts": int(to_ts),
        "tick_count": 0,
        "frame_count": len(bar_frames),
        "walk_mode": "m1-static",
        "highlight_trade_id": None,
    }


def build_period_replay(trade_rows: List[Dict[str, Any]],
                        symbol: Optional[str] = None,
                        from_ts: Optional[int] = None,
                        to_ts: Optional[int] = None) -> Dict[str, Any]:
    """Full backtest period chart — all trades in chronological order on one timeline."""
    rows = sorted(
        [r for r in (trade_rows or []) if int(r.get("entry_time") or r.get("entry_ts") or 0)],
        key=lambda r: int(r.get("entry_time") or r.get("entry_ts") or 0),
    )
    if not rows:
        return {"error": "no trades to replay"}

    sym = symbol or rows[0].get("symbol") or "ustech"
    now_ts = sim._mt5_now_ts() if sim else 0
    max_walk_sec = sim.MAX_WALK_MIN * 60 if sim else 3600

    first_entry = int(rows[0].get("entry_time") or rows[0].get("entry_ts"))
    last_exit = first_entry
    for r in rows:
        et = int(r.get("entry_time") or r.get("entry_ts") or 0)
        xt = int(r.get("exit_time") or 0)
        last_exit = max(last_exit, xt or (et + max_walk_sec))

    if from_ts is None:
        from_ts = first_entry - PRE_ENTRY_MIN * 60
    if to_ts is None:
        to_ts = last_exit + POST_EXIT_MIN * 60
    if now_ts:
        to_ts = min(int(to_ts), now_ts + 60)

    if sim:
        sim.ensure_mt5()

    m1 = fetch_m1_range(sym, int(from_ts), int(to_ts))
    candles = _rates_to_candles(m1)
    if not candles:
        return {"error": "no M1 data for period — connect MT5"}

    ticks_raw = sim.fetch_ticks(sym, int(from_ts), int(to_ts)) if sim else None
    ref_px = float(rows[0].get("entry_price") or 0)
    tick_series = _tick_series(ticks_raw)
    tick_series = sanitize_tick_series(
        tick_series, candles, ref_px, int(from_ts), int(to_ts))
    tick_series = align_ticks_to_candles(tick_series, candles)

    steps = adaptive_steps_per_bar(len(candles))
    replay_frames = build_replay_timeline(candles, tick_series, steps_per_bar=steps)
    overlay = (compute_chart_overlays_light(candles)
               if len(candles) > 500 else compute_chart_overlays(candles))

    trades: List[Dict[str, Any]] = []
    for row in rows:
        ann = annotate_trade_row(row, candles, ticks_raw)
        if ann:
            trades.append(ann)

    if not trades:
        return {"error": "could not place trades on chart"}

    return {
        "period_mode": True,
        "symbol": sym,
        "trades": trades,
        "n_trades": len(trades),
        "candles": candles,
        "ticks": tick_series,
        "replay_frames": replay_frames,
        "overlay": overlay,
        "from_ts": int(from_ts),
        "to_ts": int(to_ts),
        "tick_count": len(ticks_raw) if ticks_raw is not None else 0,
        "frame_count": len(replay_frames),
        "walk_mode": "period",
    }


def fmt_axis_time(epoch: int) -> str:
    if sim:
        full = sim._fmt_ts(epoch)
        return full[5:16] if epoch else ""
    try:
        return datetime.utcfromtimestamp(epoch).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def tick_at_index(ticks: List[Dict], idx: int) -> Tuple[int, float]:
    if not ticks:
        return 0, 0.0
    idx = max(0, min(len(ticks) - 1, idx))
    t = ticks[idx]
    return int(t["ts"]), float(t.get("mid") or 0)


def replay_candles(candles: List[Dict[str, Any]], ticks: List[Dict],
                   cursor_ts: int) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Closed M1 bars + one tick-built forming bar up to cursor_ts (MT5 tester style)."""
    if not candles or not cursor_ts:
        return [], None
    cursor_ts = int(cursor_ts)
    completed: List[Dict[str, Any]] = []
    forming: Optional[Dict[str, Any]] = None

    for c in candles:
        bar_ts = int(c["ts"])
        bar_end = bar_ts + 60
        if bar_end <= cursor_ts:
            completed.append(c)
            continue
        if bar_ts <= cursor_ts < bar_end:
            o = float(c["o"])
            m1_h, m1_l, m1_c = float(c["h"]), float(c["l"]), float(c["c"])
            frac = min(1.0, max(0.0, (cursor_ts - bar_ts) / 60.0))
            close = o + (m1_c - o) * frac
            h = max(o, close, o + max(0.0, m1_h - o) * frac)
            l = min(o, close, o - max(0.0, o - m1_l) * frac)
            bar_ticks = [
                t for t in (ticks or [])
                if bar_ts <= int(t["ts"]) <= cursor_ts and float(t.get("mid") or 0) > 0
            ]
            if bar_ticks:
                ref = close if close > 0 else (m1_h + m1_l) / 2.0
                mids = [
                    float(t["mid"]) for t in bar_ticks
                    if abs(float(t["mid"]) - ref) <= 150
                ]
                if mids:
                    h = max(h, max(mids))
                    l = min(l, min(mids))
                    close = mids[-1]
            forming = {
                "ts": bar_ts, "o": o, "h": h, "l": l, "c": close,
                "vol": c.get("vol", 0), "forming": True,
            }
            break
        break
    return completed, forming


def tick_path_to_cursor(ticks: List[Dict], cursor_ts: int,
                        max_pts: int = 600) -> List[Tuple[int, float]]:
    """(ts, mid) pairs for price trail during replay."""
    if not ticks or not cursor_ts:
        return []
    pts: List[Tuple[int, float]] = []
    for t in ticks:
        ts = int(t["ts"])
        if ts > cursor_ts:
            break
        mid = float(t.get("mid") or 0)
        if mid > 0:
            pts.append((ts, mid))
    if len(pts) <= max_pts:
        return pts
    step = max(1, len(pts) // max_pts)
    return pts[::step] + [pts[-1]]


def signal_color(sig: Optional[str]) -> str:
    if sig == "buy":
        return "#2563EB"
    if sig == "sell":
        return "#DC2626"
    return "#4B5563"
