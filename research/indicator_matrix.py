"""Unified USTECH technical-indicator matrix from stored M1 bars.

USTECH is the only instrument we trade, and the only symbol stored in the
``m1_bars`` table (client ``PLEXY``).  This module turns those 1-minute OHLCV
bars into a full indicator matrix at any resampled timeframe, plus a
last-bar signal snapshot that combines every indicator (including the ten
that previously lived as empty placeholders in ``trader_companion/signals``).

Typical use::

    from research.indicator_matrix import load_ustech_indicator_matrix
    matrix = load_ustech_indicator_matrix(timeframe="15m", lookback_days=120)
    snap = latest_signals_from_matrix(matrix)

Everything is computed with pandas/numpy only (no talib / pandas-ta) and is
causal — no indicator uses information from future bars.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from research.market_signals import bars_list_to_m1_df, resample_ohlc

DEFAULT_TIMEFRAME = "15m"
_TF_RULES = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1D",
}


# ── primitive vectorized indicators (close / OHLCV) ──────────────────────

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing (running moving average)."""
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _rma(delta.clip(lower=0), n)
    loss = _rma(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def _atr(high, low, close, n: int = 14) -> pd.Series:
    return _rma(_true_range(high, low, close), n)


def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    macd = _ema(close, fast) - _ema(close, slow)
    sig = macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd, sig, macd - sig


def _stochastic(high, low, close, k=14, d=3):
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    pk = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    return pk, pk.rolling(d, min_periods=d).mean()


def _cci(high, low, close, n=20):
    tp = (high + low + close) / 3.0
    sma = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def _williams_r(high, low, close, n=14):
    hh = high.rolling(n, min_periods=n).max()
    ll = low.rolling(n, min_periods=n).min()
    return -100 * (hh - close) / (hh - ll).replace(0, np.nan)


def _roc(close, n=12):
    return (close / close.shift(n) - 1.0) * 100.0


def _momentum(close, n=10):
    return close - close.shift(n)


def _tsi(close, long=25, short=13):
    diff = close.diff()
    abs_diff = diff.abs()
    ema1 = diff.ewm(span=long, adjust=False, min_periods=long).mean()
    ema2 = ema1.ewm(span=short, adjust=False, min_periods=short).mean()
    aema1 = abs_diff.ewm(span=long, adjust=False, min_periods=long).mean()
    aema2 = aema1.ewm(span=short, adjust=False, min_periods=short).mean()
    return 100 * ema2 / aema2.replace(0, np.nan)


def _bollinger(close, n=20, k=2.0):
    mid = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def _dmi_adx(high, low, close, n=14):
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    tr_n = _rma(_true_range(high, low, close), n)
    plus_di = 100 * _rma(plus_dm, n) / tr_n.replace(0, np.nan)
    minus_di = 100 * _rma(minus_dm, n) / tr_n.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = _rma(dx, n)
    return plus_di, minus_di, adx


def _obv(close, volume):
    sign = np.sign(close.diff().fillna(0.0))
    return (sign * volume.fillna(0.0)).cumsum()


def _mfi(high, low, close, volume, n=14):
    tp = (high + low + close) / 3.0
    rmf = tp * volume.fillna(0.0)
    pos = rmf.where(tp > tp.shift(1), 0.0)
    neg = rmf.where(tp < tp.shift(1), 0.0)
    pos_sum = pos.rolling(n, min_periods=n).sum()
    neg_sum = neg.rolling(n, min_periods=n).sum()
    mr = pos_sum / neg_sum.replace(0, np.nan)
    return 100 - (100 / (1 + mr))


def _supertrend(high, low, close, period=10, multiplier=3.0):
    atr = _atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    n = len(close)
    st = np.full(n, np.nan)
    direction = np.ones(n)
    ub = upper.to_numpy(copy=True)
    lb = lower.to_numpy(copy=True)
    c = close.to_numpy()
    for i in range(1, n):
        if np.isnan(ub[i]) or np.isnan(lb[i]):
            continue
        # carry bands forward (Supertrend "locking" rules)
        if not np.isnan(ub[i - 1]):
            ub[i] = ub[i] if (ub[i] < ub[i - 1] or c[i - 1] > ub[i - 1]) else ub[i - 1]
            lb[i] = lb[i] if (lb[i] > lb[i - 1] or c[i - 1] < lb[i - 1]) else lb[i - 1]
        if c[i] > ub[i - 1]:
            direction[i] = 1
        elif c[i] < lb[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = lb[i] if direction[i] == 1 else ub[i]
    return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)


def _parabolic_sar(high, low, step=0.02, max_step=0.2):
    h = high.to_numpy()
    l = low.to_numpy()
    n = len(h)
    sar = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=high.index)
    bull = True
    af = step
    ep = h[0]
    sar[0] = l[0]
    for i in range(1, n):
        prev = sar[i - 1]
        cur = prev + af * (ep - prev)
        if bull:
            cur = min(cur, l[i - 1], l[max(i - 2, 0)])
            if l[i] < cur:
                bull = False
                cur = ep
                ep = l[i]
                af = step
            else:
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + step, max_step)
        else:
            cur = max(cur, h[i - 1], h[max(i - 2, 0)])
            if h[i] > cur:
                bull = True
                cur = ep
                ep = h[i]
                af = step
            else:
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + step, max_step)
        sar[i] = cur
    return pd.Series(sar, index=high.index)


# ── channel / oscillator indicators (self-contained, server-owned) ───────
# These were formerly stubs in trader_companion/signals/*. Signal generation
# now lives entirely on the server, so the math is implemented here. All are
# causal — breakout bands are shifted one bar so the current bar cannot leak
# into its own channel. Inputs use lowercase OHLCV columns.

def donchian_channel(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    upper = df["high"].rolling(period, min_periods=period).max().shift(1)
    lower = df["low"].rolling(period, min_periods=period).min().shift(1)
    return pd.DataFrame({"dc_upper": upper, "dc_middle": (upper + lower) / 2.0, "dc_lower": lower})


def get_donchian_channel_signal(df: pd.DataFrame, period: int = 20) -> int:
    if df is None or len(df) < period + 1:
        return 0
    b = donchian_channel(df, period)
    u, l, c = b["dc_upper"].iloc[-1], b["dc_lower"].iloc[-1], df["close"].iloc[-1]
    if pd.isna(u) or pd.isna(l):
        return 0
    return 1 if c > u else (-1 if c < l else 0)


def price_channel(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    upper = df["close"].rolling(period, min_periods=period).max().shift(1)
    lower = df["close"].rolling(period, min_periods=period).min().shift(1)
    return pd.DataFrame({"pc_upper": upper, "pc_middle": (upper + lower) / 2.0, "pc_lower": lower})


def get_price_channel_signal(df: pd.DataFrame, period: int = 20) -> int:
    if df is None or len(df) < period + 1:
        return 0
    b = price_channel(df, period)
    u, l, c = b["pc_upper"].iloc[-1], b["pc_lower"].iloc[-1], df["close"].iloc[-1]
    if pd.isna(u) or pd.isna(l):
        return 0
    return 1 if c > u else (-1 if c < l else 0)


def keltner_channel(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    center = df["close"].ewm(span=period, adjust=False, min_periods=period).mean()
    atr = _atr(df["high"], df["low"], df["close"], period)
    return pd.DataFrame({
        "kc_upper": center + atr_mult * atr,
        "kc_middle": center,
        "kc_lower": center - atr_mult * atr,
    })


def get_keltner_channel_signal(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> int:
    if df is None or len(df) < period + 1:
        return 0
    b = keltner_channel(df, period, atr_mult)
    u, l, c = b["kc_upper"].iloc[-1], b["kc_lower"].iloc[-1], df["close"].iloc[-1]
    if pd.isna(u) or pd.isna(l):
        return 0
    return 1 if c > u else (-1 if c < l else 0)


def vortex(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    tr = _true_range(high, low, close)
    vm_plus = (high - low.shift(1)).abs()
    vm_minus = (low - high.shift(1)).abs()
    tr_sum = tr.rolling(period, min_periods=period).sum()
    return pd.DataFrame({
        "vi_plus": vm_plus.rolling(period, min_periods=period).sum() / tr_sum,
        "vi_minus": vm_minus.rolling(period, min_periods=period).sum() / tr_sum,
    })


def get_vortex_signal(df: pd.DataFrame, period: int = 14) -> int:
    if df is None or len(df) < period + 1:
        return 0
    v = vortex(df, period)
    vp, vm = v["vi_plus"].iloc[-1], v["vi_minus"].iloc[-1]
    if pd.isna(vp) or pd.isna(vm):
        return 0
    return 1 if vp > vm else (-1 if vm > vp else 0)


def cmo(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(period, min_periods=period).sum()
    down = (-delta.clip(upper=0)).rolling(period, min_periods=period).sum()
    denom = (up + down).replace(0, np.nan)
    return (100 * (up - down) / denom).astype(float)


def get_cmo_signal(df: pd.DataFrame, period: int = 14, overbought: float = 50.0,
                   oversold: float = -50.0) -> int:
    if df is None or len(df) < period + 1:
        return 0
    val = cmo(df, period).iloc[-1]
    if pd.isna(val):
        return 0
    return 1 if val <= oversold else (-1 if val >= overbought else 0)


def coppock_curve(df: pd.DataFrame, wma_period: int = 10, roc1: int = 14, roc2: int = 11) -> pd.Series:
    roc_sum = _roc(df["close"], roc1) + _roc(df["close"], roc2)
    weights = np.arange(1, wma_period + 1, dtype=float)
    wsum = weights.sum()
    return roc_sum.rolling(wma_period, min_periods=wma_period).apply(
        lambda x: float((x * weights).sum() / wsum), raw=True
    )


def get_coppock_curve_signal(df: pd.DataFrame, wma_period: int = 10, roc1: int = 14, roc2: int = 11) -> int:
    if df is None or len(df) < max(roc1, roc2) + wma_period + 2:
        return 0
    cc = coppock_curve(df, wma_period, roc1, roc2)
    cur, prev = cc.iloc[-1], cc.iloc[-2]
    if pd.isna(cur) or pd.isna(prev):
        return 0
    return 1 if cur > prev else (-1 if cur < prev else 0)


def ultimate_oscillator(df: pd.DataFrame, short: int = 7, medium: int = 14, long: int = 28) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_low = pd.concat([low, prev_close], axis=1).min(axis=1)
    true_high = pd.concat([high, prev_close], axis=1).max(axis=1)
    bp = close - true_low
    tr = true_high - true_low

    def _avg(n):
        return bp.rolling(n, min_periods=n).sum() / tr.rolling(n, min_periods=n).sum().replace(0, np.nan)

    return (100 * (4 * _avg(short) + 2 * _avg(medium) + _avg(long)) / 7).astype(float)


def get_ultimate_oscillator_signal(df: pd.DataFrame, short: int = 7, medium: int = 14, long: int = 28,
                                   overbought: float = 70.0, oversold: float = 30.0) -> int:
    if df is None or len(df) < long + 2:
        return 0
    val = ultimate_oscillator(df, short, medium, long).iloc[-1]
    if pd.isna(val):
        return 0
    return 1 if val <= oversold else (-1 if val >= overbought else 0)


def elder_ray(df: pd.DataFrame, period: int = 13) -> pd.DataFrame:
    ema = df["close"].ewm(span=period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({
        "er_ema": ema,
        "bull_power": df["high"] - ema,
        "bear_power": df["low"] - ema,
    })


def get_elder_ray_signal(df: pd.DataFrame, period: int = 13) -> int:
    if df is None or len(df) < period + 2:
        return 0
    er = elder_ray(df, period)
    ema, bull, bear = er["er_ema"], er["bull_power"], er["bear_power"]
    if pd.isna(ema.iloc[-1]) or pd.isna(ema.iloc[-2]):
        return 0
    if ema.iloc[-1] > ema.iloc[-2] and bear.iloc[-1] < 0 and bear.iloc[-1] > bear.iloc[-2]:
        return 1
    if ema.iloc[-1] < ema.iloc[-2] and bull.iloc[-1] > 0 and bull.iloc[-1] < bull.iloc[-2]:
        return -1
    return 0


def _smma(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _alligator(df: pd.DataFrame) -> pd.DataFrame:
    median = (df["high"] + df["low"]) / 2.0
    return pd.DataFrame({
        "jaw": _smma(median, 13).shift(8),
        "teeth": _smma(median, 8).shift(5),
        "lips": _smma(median, 5).shift(3),
    })


def gator_oscillator(df: pd.DataFrame) -> pd.DataFrame:
    a = _alligator(df)
    return pd.DataFrame({
        "gator_upper": (a["jaw"] - a["teeth"]).abs(),
        "gator_lower": -(a["teeth"] - a["lips"]).abs(),
    })


def get_gator_oscillator_signal(df: pd.DataFrame) -> int:
    if df is None or len(df) < 30:
        return 0
    a = _alligator(df)
    jaw, teeth, lips = a["jaw"].iloc[-1], a["teeth"].iloc[-1], a["lips"].iloc[-1]
    if pd.isna(jaw) or pd.isna(teeth) or pd.isna(lips):
        return 0
    if lips > teeth > jaw:
        return 1
    if lips < teeth < jaw:
        return -1
    return 0


def fractals(df: pd.DataFrame) -> pd.DataFrame:
    high, low = df["high"], df["low"]
    up = ((high > high.shift(1)) & (high > high.shift(2))
          & (high > high.shift(-1)) & (high > high.shift(-2)))
    down = ((low < low.shift(1)) & (low < low.shift(2))
            & (low < low.shift(-1)) & (low < low.shift(-2)))
    return pd.DataFrame({"up_fractal": up.fillna(False), "down_fractal": down.fillna(False)})


def get_fractal_signal(df: pd.DataFrame) -> int:
    if df is None or len(df) < 6:
        return 0
    fr = fractals(df).iloc[:-2]  # last 2 bars unconfirmed
    high, low, close = df["high"].iloc[:-2], df["low"].iloc[:-2], df["close"]
    up_levels = high[fr["up_fractal"].values]
    down_levels = low[fr["down_fractal"].values]
    last_up = float(up_levels.iloc[-1]) if len(up_levels) else None
    last_down = float(down_levels.iloc[-1]) if len(down_levels) else None
    c = float(close.iloc[-1])
    if last_up is not None and c > last_up:
        return 1
    if last_down is not None and c < last_down:
        return -1
    return 0


# ── matrix builders ──────────────────────────────────────────────────────

def build_indicator_matrix(m1: pd.DataFrame, timeframe: str = DEFAULT_TIMEFRAME) -> pd.DataFrame:
    """Resample M1 to `timeframe` and append every indicator as a column.

    `m1` must be a UTC/EAT-indexed OHLCV frame (e.g. from
    ``research.market_signals.bars_list_to_m1_df``).
    """
    if m1 is None or m1.empty:
        return pd.DataFrame()
    rule = _TF_RULES.get(timeframe, timeframe)
    ohlc = resample_ohlc(m1, rule) if timeframe != "1m" else m1.copy()
    if ohlc.empty:
        return pd.DataFrame()

    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    vol = ohlc["tick_volume"] if "tick_volume" in ohlc.columns else pd.Series(0.0, index=ohlc.index)
    out = ohlc.copy()

    # Trend / moving averages
    out["sma_20"] = _sma(c, 20)
    out["ema_9"] = _ema(c, 9)
    out["ema_21"] = _ema(c, 21)
    out["ema_50"] = _ema(c, 50)
    macd, macd_sig, macd_hist = _macd(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd, macd_sig, macd_hist

    # Momentum / oscillators
    out["rsi_14"] = _rsi(c, 14)
    k, d = _stochastic(h, l, c)
    out["stoch_k"], out["stoch_d"] = k, d
    out["cci_20"] = _cci(h, l, c, 20)
    out["williams_r"] = _williams_r(h, l, c, 14)
    out["roc_12"] = _roc(c, 12)
    out["momentum_10"] = _momentum(c, 10)
    out["tsi"] = _tsi(c)
    out["cmo_14"] = cmo(ohlc, 14)
    out["ultimate_osc"] = ultimate_oscillator(ohlc)
    out["coppock"] = coppock_curve(ohlc)

    # Volatility / bands
    out["atr_14"] = _atr(h, l, c, 14)
    bb_u, bb_m, bb_l = _bollinger(c)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = bb_u, bb_m, bb_l
    kc = keltner_channel(ohlc)
    out["kc_upper"], out["kc_middle"], out["kc_lower"] = kc["kc_upper"], kc["kc_middle"], kc["kc_lower"]
    dc = donchian_channel(ohlc)
    out["dc_upper"], out["dc_middle"], out["dc_lower"] = dc["dc_upper"], dc["dc_middle"], dc["dc_lower"]
    pc = price_channel(ohlc)
    out["pc_upper"], out["pc_middle"], out["pc_lower"] = pc["pc_upper"], pc["pc_middle"], pc["pc_lower"]

    # Trend strength / direction
    plus_di, minus_di, adx = _dmi_adx(h, l, c, 14)
    out["plus_di"], out["minus_di"], out["adx"] = plus_di, minus_di, adx
    vi = vortex(ohlc)
    out["vi_plus"], out["vi_minus"] = vi["vi_plus"], vi["vi_minus"]
    st, st_dir = _supertrend(h, l, c)
    out["supertrend"], out["supertrend_dir"] = st, st_dir
    out["psar"] = _parabolic_sar(h, l)

    # Volume
    out["obv"] = _obv(c, vol)
    out["mfi_14"] = _mfi(h, l, c, vol, 14)

    # Elder Ray / Gator / Fractals
    er = elder_ray(ohlc)
    out["bull_power"], out["bear_power"] = er["bull_power"], er["bear_power"]
    g = gator_oscillator(ohlc)
    out["gator_upper"], out["gator_lower"] = g["gator_upper"], g["gator_lower"]
    fr = fractals(ohlc)
    out["up_fractal"], out["down_fractal"] = fr["up_fractal"], fr["down_fractal"]

    return out


def latest_signals_from_ohlc(ohlc: pd.DataFrame) -> Dict[str, int]:
    """Combine every indicator into a -1/0/+1 snapshot on the last bar.

    Returns a dict keyed by indicator name plus a ``consensus`` (mean of all
    non-zero votes, rounded to sign) and ``vote_sum``.
    """
    if ohlc is None or ohlc.empty:
        return {}
    c = ohlc["close"]
    sig: Dict[str, int] = {}

    def s(name, v):
        sig[name] = int(v) if v is not None else 0

    # classic indicators -> simple causal rules
    macd, macd_sig, _ = _macd(c)
    s("macd", 1 if macd.iloc[-1] > macd_sig.iloc[-1] else -1)
    rsi = _rsi(c, 14).iloc[-1]
    s("rsi", 1 if rsi < 30 else (-1 if rsi > 70 else 0))
    k, d = _stochastic(ohlc["high"], ohlc["low"], c)
    s("stochastic", 1 if (k.iloc[-1] < 20 and k.iloc[-1] > d.iloc[-1]) else (-1 if (k.iloc[-1] > 80 and k.iloc[-1] < d.iloc[-1]) else 0))
    cci = _cci(ohlc["high"], ohlc["low"], c).iloc[-1]
    s("cci", 1 if cci < -100 else (-1 if cci > 100 else 0))
    wr = _williams_r(ohlc["high"], ohlc["low"], c).iloc[-1]
    s("williams_r", 1 if wr < -80 else (-1 if wr > -20 else 0))
    s("roc", 1 if _roc(c).iloc[-1] > 0 else -1)
    s("momentum", 1 if _momentum(c).iloc[-1] > 0 else -1)
    s("tsi", 1 if _tsi(c).iloc[-1] > 0 else -1)
    ema9, ema21 = _ema(c, 9).iloc[-1], _ema(c, 21).iloc[-1]
    s("ema_cross", 1 if ema9 > ema21 else -1)
    bb_u, _, bb_l = _bollinger(c)
    s("bollinger", 1 if c.iloc[-1] < bb_l.iloc[-1] else (-1 if c.iloc[-1] > bb_u.iloc[-1] else 0))
    plus_di, minus_di, adx = _dmi_adx(ohlc["high"], ohlc["low"], c)
    s("adx", (1 if plus_di.iloc[-1] > minus_di.iloc[-1] else -1) if adx.iloc[-1] > 25 else 0)
    st, st_dir = _supertrend(ohlc["high"], ohlc["low"], c)
    s("supertrend", 1 if st_dir.iloc[-1] > 0 else -1)
    psar = _parabolic_sar(ohlc["high"], ohlc["low"]).iloc[-1]
    s("psar", 1 if c.iloc[-1] > psar else -1)
    mfi = _mfi(ohlc["high"], ohlc["low"], c, ohlc.get("tick_volume", pd.Series(0.0, index=c.index))).iloc[-1]
    s("mfi", 1 if mfi < 20 else (-1 if mfi > 80 else 0))
    obv = _obv(c, ohlc.get("tick_volume", pd.Series(0.0, index=c.index)))
    s("obv", 1 if obv.iloc[-1] > obv.iloc[-2] else -1)

    # the ten (formerly placeholder) indicators — reuse their signal functions
    s("donchian", get_donchian_channel_signal(ohlc))
    s("price_channel", get_price_channel_signal(ohlc))
    s("keltner", get_keltner_channel_signal(ohlc))
    s("vortex", get_vortex_signal(ohlc))
    s("cmo", get_cmo_signal(ohlc))
    s("coppock", get_coppock_curve_signal(ohlc))
    s("ultimate_osc", get_ultimate_oscillator_signal(ohlc))
    s("elder_ray", get_elder_ray_signal(ohlc))
    s("gator", get_gator_oscillator_signal(ohlc))
    s("fractal", get_fractal_signal(ohlc))

    votes = [v for v in sig.values() if v in (-1, 1)]
    vote_sum = int(sum(votes))
    sig["vote_sum"] = vote_sum
    sig["consensus"] = int(np.sign(vote_sum))
    return sig


def latest_signals_from_matrix(matrix: pd.DataFrame) -> Dict[str, int]:
    """Convenience: derive the signal snapshot from a built matrix."""
    cols = ["open", "high", "low", "close"]
    if "tick_volume" in matrix.columns:
        cols.append("tick_volume")
    return latest_signals_from_ohlc(matrix[cols])


def list_indicators() -> List[str]:
    """All indicator column names produced by build_indicator_matrix."""
    return [
        "sma_20", "ema_9", "ema_21", "ema_50", "macd", "macd_signal", "macd_hist",
        "rsi_14", "stoch_k", "stoch_d", "cci_20", "williams_r", "roc_12",
        "momentum_10", "tsi", "cmo_14", "ultimate_osc", "coppock",
        "atr_14", "bb_upper", "bb_middle", "bb_lower",
        "kc_upper", "kc_middle", "kc_lower", "dc_upper", "dc_middle", "dc_lower",
        "pc_upper", "pc_middle", "pc_lower",
        "plus_di", "minus_di", "adx", "vi_plus", "vi_minus",
        "supertrend", "supertrend_dir", "psar", "obv", "mfi_14",
        "bull_power", "bear_power", "gator_upper", "gator_lower",
        "up_fractal", "down_fractal",
    ]


def load_ustech_indicator_matrix(
    timeframe: str = DEFAULT_TIMEFRAME,
    lookback_days: Optional[int] = None,
    limit: int = 200_000,
    client_id: str = "PLEXY",
    symbol: str = "USTECH",
) -> pd.DataFrame:
    """Load stored USTECH M1 bars and return the full indicator matrix.

    Requires DB access (dashboard.ml_predictions_service.fetch_m1_bars_for_ml).
    """
    import time as _time
    from dashboard.ml_predictions_service import fetch_m1_bars_for_ml

    start_time = None
    if lookback_days:
        start_time = int(_time.time()) - int(lookback_days) * 86400
    bars = fetch_m1_bars_for_ml(
        client_id=client_id, symbol=symbol, start_time=start_time, limit=limit
    )
    m1 = bars_list_to_m1_df(bars)
    return build_indicator_matrix(m1, timeframe)
