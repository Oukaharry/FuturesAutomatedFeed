"""Automatic indicator-parameter optimization for the signal vote.

On startup (once MT5 bars are available) every tunable voter indicator is
backtested over a grid of candidate settings against ACTUAL forward returns:
for each parameter combo the indicator's historical -1/0/+1 signal series is
computed bar-by-bar (vectorized, causal) and scored by how often a non-neutral
signal matched the direction of the next ``HORIZON_BARS`` move. The winning
settings are persisted to disk and applied to the live vote, so the vote
always runs with the parameters that actually predicted this market best —
no guessed defaults, no manual tuning.

Public API (mirrors ml_direction's style):
    ensure_optimized_async(symbol, log_fn=None)   # background, throttled
    get_best_params(symbol) -> {indicator: kwargs}
    optimize(symbol, log_fn=None) -> result dict  # blocking
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from trader_companion.signals import ml_direction as _md
except ImportError:
    try:
        from signals import ml_direction as _md
    except ImportError:
        import ml_direction as _md

OPT_VERSION = 1
OPT_BARS = 6000               # ~3 weeks of M5
HORIZON_BARS = 4              # same look-ahead the ML trains on (20 min on M5)
MIN_SIGNALS = 30              # combos firing less than this can't be trusted
REOPTIMIZE_INTERVAL_SEC = 24 * 3600

_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_optimizing: set = set()
_optimizing_lock = threading.Lock()


def _params_path(symbol: str, timeframe_minutes: int) -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, f"indicator_params_{symbol.lower()}_m{timeframe_minutes}.json")


# ── vectorized sign-series builders (mirror the live voter rules) ────────

def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _sign(buy, sell, index) -> pd.Series:
    return pd.Series(np.where(buy, 1.0, np.where(sell, -1.0, 0.0)), index=index)


def _true_range(h, l, c):
    prev = c.shift(1)
    return pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)


def _sig_rsi(df, period=14, overbought=70, oversold=30):
    c = df["close"]
    delta = c.diff()
    rsi = 100 - 100 / (1 + _rma(delta.clip(lower=0), period)
                       / _rma(-delta.clip(upper=0), period).replace(0, np.nan))
    return _sign(rsi <= oversold, rsi >= overbought, df.index)


def _sig_stochastic(df, k_period=14, d_period=3, overbought=80, oversold=20):
    h, l, c = df["high"], df["low"], df["close"]
    ll = l.rolling(k_period, min_periods=k_period).min()
    hh = h.rolling(k_period, min_periods=k_period).max()
    k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    return _sign(k < oversold, k > overbought, df.index)


def _sig_macd(df, fast_period=12, slow_period=26, signal_period=9):
    c = df["close"]
    macd = _ema(c, fast_period) - _ema(c, slow_period)
    sig = macd.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
    return _sign(macd > sig, macd < sig, df.index)


def _sig_sma(df, period=21):
    ma = df["close"].rolling(period, min_periods=period).mean()
    return _sign(df["close"] > ma, df["close"] < ma, df.index)


def _sig_ema(df, period=21):
    ma = _ema(df["close"], period)
    return _sign(df["close"] > ma, df["close"] < ma, df.index)


def _sig_cci(df, period=20, overbought=100, oversold=-100):
    h, l, c = df["high"], df["low"], df["close"]
    tp = (h + l + c) / 3.0
    sma = tp.rolling(period, min_periods=period).mean()
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
    return _sign(cci < oversold, cci > overbought, df.index)


def _sig_wr(df, period=14, overbought=-20, oversold=-80):
    h, l, c = df["high"], df["low"], df["close"]
    hh = h.rolling(period, min_periods=period).max()
    ll = l.rolling(period, min_periods=period).min()
    wr = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    return _sign(wr < oversold, wr > overbought, df.index)


def _sig_mfi(df, period=14, overbought=80, oversold=20):
    h, l, c, v = df["high"], df["low"], df["close"], df["tick_volume"]
    tp = (h + l + c) / 3.0
    rmf = tp * v.fillna(0.0)
    pos = rmf.where(tp > tp.shift(1), 0.0).rolling(period, min_periods=period).sum()
    neg = rmf.where(tp < tp.shift(1), 0.0).rolling(period, min_periods=period).sum()
    mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    return _sign(mfi < oversold, mfi > overbought, df.index)


def _sig_roc(df, period=12, threshold=0):
    roc = (df["close"] / df["close"].shift(period) - 1.0) * 100.0
    return _sign(roc > threshold, roc < -threshold, df.index)


def _sig_momentum(df, period=10, threshold=0.3):
    mom = df["close"] - df["close"].shift(period)
    return _sign(mom > threshold, mom < -threshold, df.index)


def _sig_tsi(df, r=25, s=13):
    diff = df["close"].diff()
    num = diff.ewm(span=s, adjust=False, min_periods=s).mean() \
        .ewm(span=r, adjust=False, min_periods=r).mean()
    den = diff.abs().ewm(span=s, adjust=False, min_periods=s).mean() \
        .ewm(span=r, adjust=False, min_periods=r).mean()
    tsi = 100 * num / den.replace(0, np.nan)
    return _sign(tsi > 25, tsi < -25, df.index)


def _sig_bb(df, period=20, deviation=2.0):
    c = df["close"]
    mid = c.rolling(period, min_periods=period).mean()
    sd = c.rolling(period, min_periods=period).std()
    return _sign(c < mid - deviation * sd, c > mid + deviation * sd, df.index)


def _sig_dmi(df, period=14, threshold=25):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr = _true_range(h, l, c).rolling(period, min_periods=period).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period, min_periods=period).mean() / atr
    return _sign((plus_di > minus_di) & (plus_di > threshold),
                 (minus_di > plus_di) & (minus_di > threshold), df.index)


def _sig_donchian(df, period=20):
    hi = df["high"].rolling(period, min_periods=period).max().shift(1)
    lo = df["low"].rolling(period, min_periods=period).min().shift(1)
    return _sign(df["close"] > hi, df["close"] < lo, df.index)


def _sig_price_channel(df, period=20):
    hi = df["close"].rolling(period, min_periods=period).max().shift(1)
    lo = df["close"].rolling(period, min_periods=period).min().shift(1)
    return _sign(df["close"] > hi, df["close"] < lo, df.index)


def _sig_keltner(df, period=20, atr_mult=2.0):
    h, l, c = df["high"], df["low"], df["close"]
    center = _ema(c, period)
    atr = _true_range(h, l, c).ewm(alpha=1.0 / period, adjust=False,
                                   min_periods=period).mean()
    return _sign(c > center + atr_mult * atr, c < center - atr_mult * atr, df.index)


def _sig_vortex(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr_sum = _true_range(h, l, c).rolling(period, min_periods=period).sum().replace(0, np.nan)
    vi_plus = (h - l.shift(1)).abs().rolling(period, min_periods=period).sum() / tr_sum
    vi_minus = (l - h.shift(1)).abs().rolling(period, min_periods=period).sum() / tr_sum
    return _sign(vi_plus > vi_minus, vi_minus > vi_plus, df.index)


def _sig_cmo(df, period=14, overbought=50, oversold=-50):
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(period, min_periods=period).sum()
    down = (-delta.clip(upper=0)).rolling(period, min_periods=period).sum()
    cmo = 100 * (up - down) / (up + down).replace(0, np.nan)
    return _sign(cmo <= oversold, cmo >= overbought, df.index)


def _sig_uo(df, short=7, medium=14, long=28, overbought=70, oversold=30):
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    true_low = pd.concat([l, prev], axis=1).min(axis=1)
    true_high = pd.concat([h, prev], axis=1).max(axis=1)
    bp = c - true_low
    tr = true_high - true_low

    def _avg(n):
        return bp.rolling(n, min_periods=n).sum() \
            / tr.rolling(n, min_periods=n).sum().replace(0, np.nan)

    uo = 100 * (4 * _avg(short) + 2 * _avg(medium) + _avg(long)) / 7
    return _sign(uo <= oversold, uo >= overbought, df.index)


def _sig_supertrend(df, period=10, multiplier=3.0):
    return _md._supertrend_dir(df["high"], df["low"], df["close"],
                               period=period, multiplier=multiplier)


# name → (sign builder, parameter grid). Grid order matters: the FIRST combo
# is the module default — on a scoring tie the default wins (stability).
GRIDS: Dict[str, Any] = {
    "RSI": (_sig_rsi, {"period": [14, 7, 21], "overbought": [70, 80], "oversold": [30, 20]}),
    "Stochastic": (_sig_stochastic, {"k_period": [14, 9, 21], "overbought": [80, 90], "oversold": [20, 10]}),
    "MACD": (_sig_macd, {"fast_period": [12, 8, 5], "slow_period": [26, 17, 35], "signal_period": [9, 5]}),
    "SMA": (_sig_sma, {"period": [21, 10, 50]}),
    "EMA": (_sig_ema, {"period": [21, 9, 50]}),
    "CCI": (_sig_cci, {"period": [20, 14], "overbought": [100, 150], "oversold": [-100, -150]}),
    "WilliamsR": (_sig_wr, {"period": [14, 10, 21], "overbought": [-20, -10], "oversold": [-80, -90]}),
    "MFI": (_sig_mfi, {"period": [14, 10], "overbought": [80, 90], "oversold": [20, 10]}),
    "ROC": (_sig_roc, {"period": [12, 6, 20]}),
    "Momentum": (_sig_momentum, {"period": [10, 5, 20]}),
    "TSI": (_sig_tsi, {"r": [25, 13], "s": [13, 7]}),
    "BollingerBands": (_sig_bb, {"period": [20, 14], "deviation": [2.0, 2.5]}),
    "DMI": (_sig_dmi, {"period": [14, 21], "threshold": [25, 20]}),
    "Donchian": (_sig_donchian, {"period": [20, 10, 40]}),
    "PriceChannel": (_sig_price_channel, {"period": [20, 10, 40]}),
    "Keltner": (_sig_keltner, {"period": [20, 14], "atr_mult": [2.0, 1.5]}),
    "Vortex": (_sig_vortex, {"period": [14, 21]}),
    "CMO": (_sig_cmo, {"period": [14, 9], "overbought": [50, 60], "oversold": [-50, -60]}),
    "UltimateOsc": (_sig_uo, {"overbought": [70, 65], "oversold": [30, 35]}),
    "Supertrend": (_sig_supertrend, {"period": [10, 7, 14], "multiplier": [3.0, 2.0]}),
}

# MACD combos where fast >= slow make no sense — filtered in _combos().


def _combos(grid: Dict[str, List]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    out = []
    for values in itertools.product(*(grid[k] for k in keys)):
        combo = dict(zip(keys, values))
        if "fast_period" in combo and "slow_period" in combo \
                and combo["fast_period"] >= combo["slow_period"]:
            continue
        out.append(combo)
    return out


def _score(sig: pd.Series, fwd: pd.Series) -> Dict[str, Any]:
    """Directional accuracy of non-neutral signals vs the forward move."""
    mask = (sig != 0) & fwd.notna() & (fwd != 0)
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "accuracy": None}
    correct = (np.sign(fwd[mask]) == np.sign(sig[mask]))
    return {"n": n, "accuracy": round(float(correct.mean()), 4)}


def optimize(symbol: str = "ustech", timeframe_minutes: int = 5,
             bars: int = OPT_BARS, horizon: int = HORIZON_BARS,
             rates=None, log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Backtest every grid combo and persist the winners. Blocking."""
    def log(msg):
        if log_fn:
            try:
                log_fn(msg)
            except Exception:
                pass

    if rates is None:
        rates = _md._fetch_rates(symbol, timeframe_minutes, bars)
    df = _md.rates_to_df(rates)
    if len(df) < 500:
        log(f"⚙ optimizer: insufficient bars ({len(df)}) — keeping defaults")
        return {"optimized": False, "reason": f"insufficient bars ({len(df)})"}

    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    best_params: Dict[str, Dict[str, Any]] = {}
    report: Dict[str, Dict[str, Any]] = {}

    for name, (builder, grid) in GRIDS.items():
        best = None
        for i, combo in enumerate(_combos(grid)):
            try:
                sig = builder(df, **combo)
            except Exception:
                continue
            sc = _score(sig, fwd)
            if sc["accuracy"] is None or sc["n"] < MIN_SIGNALS:
                continue
            # strictly better accuracy wins; the first (default) combo wins ties
            if best is None or sc["accuracy"] > best["accuracy"]:
                best = {"params": combo, "accuracy": sc["accuracy"],
                        "n": sc["n"], "is_default": i == 0}
        if best:
            report[name] = best
            if not best["is_default"]:
                best_params[name] = best["params"]

    result = {
        "optimized": True,
        "version": OPT_VERSION,
        "symbol": symbol.lower(),
        "timeframe_minutes": timeframe_minutes,
        "optimized_at": time.time(),
        "n_bars": len(df),
        "horizon": horizon,
        "params": best_params,
        "report": report,
    }
    with _cache_lock:
        _cache[f"{symbol.lower()}_m{timeframe_minutes}"] = result
    try:
        with open(_params_path(symbol, timeframe_minutes), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    except Exception:
        pass

    tuned = ", ".join(f"{k}={v['params']} acc={v['accuracy']:.0%}"
                      for k, v in report.items() if not v["is_default"]) or "none (defaults already best)"
    log(f"⚙ optimizer: {len(df)} bars, {len(report)} indicators scored — tuned: {tuned}")
    return result


def _load_result(symbol: str, timeframe_minutes: int) -> Optional[Dict[str, Any]]:
    key = f"{symbol.lower()}_m{timeframe_minutes}"
    with _cache_lock:
        r = _cache.get(key)
    if r:
        return r
    try:
        path = _params_path(symbol, timeframe_minutes)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            r = json.load(f)
        if r.get("version") != OPT_VERSION:
            return None
        with _cache_lock:
            _cache[key] = r
        return r
    except Exception:
        return None


def get_best_params(symbol: str = "ustech",
                    timeframe_minutes: int = 5) -> Dict[str, Dict[str, Any]]:
    """Optimized kwargs per indicator name ({} → module defaults are best)."""
    r = _load_result(symbol, timeframe_minutes)
    if not r or not r.get("optimized"):
        return {}
    return r.get("params") or {}


def last_optimized_at(symbol: str = "ustech", timeframe_minutes: int = 5) -> Optional[float]:
    r = _load_result(symbol, timeframe_minutes)
    return r.get("optimized_at") if r else None


def is_optimizing(symbol: str = "ustech", timeframe_minutes: int = 5) -> bool:
    with _optimizing_lock:
        return f"{symbol.lower()}_m{timeframe_minutes}" in _optimizing


def ensure_optimized_async(symbol: str = "ustech", timeframe_minutes: int = 5,
                           log_fn: Optional[Callable[[str], None]] = None) -> bool:
    """Run optimization in the background if results are missing/stale.

    Returns True when fresh optimized params already exist.
    """
    r = _load_result(symbol, timeframe_minutes)
    if r and time.time() - r.get("optimized_at", 0) < REOPTIMIZE_INTERVAL_SEC:
        return True
    if not MT5_AVAILABLE:
        return False
    key = f"{symbol.lower()}_m{timeframe_minutes}"
    with _optimizing_lock:
        if key in _optimizing:
            return False
        _optimizing.add(key)

    def _run():
        try:
            if log_fn:
                log_fn("⚙ optimizer: backtesting indicator settings against "
                       "recent bars (background)…")
            optimize(symbol, timeframe_minutes, log_fn=log_fn)
        except Exception as e:
            if log_fn:
                try:
                    log_fn(f"⚙ optimizer error: {e}")
                except Exception:
                    pass
        finally:
            with _optimizing_lock:
                _optimizing.discard(key)

    threading.Thread(target=_run, name=f"ind-opt-{symbol}", daemon=True).start()
    return False
