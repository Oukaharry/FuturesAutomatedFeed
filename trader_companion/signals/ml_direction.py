"""Local ML + deep-learning direction engine for the companion AI.

Trains two estimators on MT5 OHLCV bars fetched on the trader's machine:

  * ML:  HistGradientBoostingClassifier (gradient-boosted trees, NaN-native)
  * DL:  MLPClassifier — feed-forward deep neural network (2 hidden layers)

They are soft-vote ensembled and confidence-gated: a buy/sell is emitted only
when the ensemble probability clears ``CONFIDENCE_THRESHOLD``; otherwise the
caller falls back to its next intelligence layer (dashboard insights or the
classic indicator vote).

Validation is expanding-window walk-forward — the reported accuracy is
strictly out-of-sample, so the caller can judge how much to trust the model.

Training runs in a background thread (``ensure_trained_async``) so the UI and
trade execution never block; models are cached in-process and retrained at
most every ``RETRAIN_INTERVAL_SEC``.
"""

from __future__ import annotations

import os
import pickle
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# Self-learning journal: predictions are recorded, verified against the
# actual market move / TP-SL simulation, and the verified accuracy feeds
# back into the confidence gate (see get_ml_direction).
try:
    from trader_companion.signals import prediction_tracker
except ImportError:
    try:
        from signals import prediction_tracker
    except ImportError:
        try:
            import prediction_tracker
        except ImportError:
            prediction_tracker = None

MODEL_VERSION = 4             # bump when make_features / ensemble changes
TRAIN_BARS = 20000            # ~70 days of M5
PREDICT_BARS = 300            # rolling-window warmup for the last row
HORIZON_BARS = 4              # 4 x M5 = 20 minutes ahead
DEADZONE_PCT = 0.0005         # |move| below 5 bps dropped from training
CONFIDENCE_THRESHOLD = 0.60
MIN_TRAIN_ROWS = 500
WALK_FORWARD_FOLDS = 4
RETRAIN_INTERVAL_SEC = 6 * 3600
TICK_LOOKBACK_SEC = 300       # 5 minutes of live ticks for microstructure
MAX_TICK_SAMPLE = 4000
VOLATILE_ATR_REGIME = 1.12    # ATR above this → volatile session
VOLATILE_TICK_SCORE = 0.50    # tick realized-vol score threshold
VOLATILE_GATE_RELAX = 0.04    # easier to act when vol is elevated

_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_training: set = set()
_training_lock = threading.Lock()


# ── disk persistence (survive app restarts; avoid cold-start fallback) ──

def _model_cache_dir() -> str:
    """Writable dir for cached models (next to exe when frozen, else module)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _model_cache_path(symbol: str, timeframe_minutes: int) -> str:
    return os.path.join(_model_cache_dir(),
                        f"ml_model_{symbol.lower()}_m{timeframe_minutes}.pkl")


def _save_bundle_to_disk(symbol: str, timeframe_minutes: int,
                         bundle: Dict[str, Any]) -> None:
    try:
        payload = {k: bundle[k] for k in
                   ("gbm", "mlp", "et", "feature_columns", "used_columns",
                    "walk_forward", "n_labeled", "trained_at")}
        payload["version"] = MODEL_VERSION
        with open(_model_cache_path(symbol, timeframe_minutes), "wb") as f:
            pickle.dump(payload, f)
    except Exception:
        pass  # persistence is best-effort; in-memory cache still works


def _load_bundle_from_disk(symbol: str,
                           timeframe_minutes: int) -> Optional[Dict[str, Any]]:
    path = _model_cache_path(symbol, timeframe_minutes)
    try:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            payload = pickle.load(f)
        if payload.get("version") != MODEL_VERSION:
            return None  # stale feature set — force retrain
        payload["trained"] = True
        return payload
    except Exception:
        return None


# ── bars → DataFrame ─────────────────────────────────────────────────────

def rates_to_df(rates) -> pd.DataFrame:
    """Normalize MT5 ``copy_rates_from_pos`` output to an OHLCV DataFrame."""
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    arr = np.asarray(rates)
    try:  # structured array with named fields
        df = pd.DataFrame({
            "time": arr["time"].astype(np.int64),
            "open": arr["open"].astype(float),
            "high": arr["high"].astype(float),
            "low": arr["low"].astype(float),
            "close": arr["close"].astype(float),
            "tick_volume": arr["tick_volume"].astype(float),
        })
    except (KeyError, IndexError, ValueError):  # plain tuples
        df = pd.DataFrame(
            [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rates],
            columns=["time", "open", "high", "low", "close", "tick_volume"],
        )
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.drop(columns=["time"]).sort_index()


# ── features / labels ────────────────────────────────────────────────────

def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _supertrend_dir(h: pd.Series, l: pd.Series, c: pd.Series,
                    period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Supertrend direction per bar (+1 up / -1 down), causal."""
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = _rma(tr, period)
    hl2 = (h + l) / 2.0
    ub = (hl2 + multiplier * atr).to_numpy(copy=True)
    lb = (hl2 - multiplier * atr).to_numpy(copy=True)
    cv = c.to_numpy()
    n = len(cv)
    direction = np.ones(n)
    for i in range(1, n):
        if np.isnan(ub[i]) or np.isnan(lb[i]):
            continue
        if not np.isnan(ub[i - 1]):
            ub[i] = ub[i] if (ub[i] < ub[i - 1] or cv[i - 1] > ub[i - 1]) else ub[i - 1]
            lb[i] = lb[i] if (lb[i] > lb[i - 1] or cv[i - 1] < lb[i - 1]) else lb[i - 1]
        if cv[i] > ub[i - 1]:
            direction[i] = 1
        elif cv[i] < lb[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=c.index)


def _psar_series(h: pd.Series, l: pd.Series,
                 step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    """Parabolic SAR value per bar, causal."""
    hv, lv = h.to_numpy(), l.to_numpy()
    n = len(hv)
    sar = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=h.index)
    bull = True
    af = step
    ep = hv[0]
    sar[0] = lv[0]
    for i in range(1, n):
        cur = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            cur = min(cur, lv[i - 1], lv[max(i - 2, 0)])
            if lv[i] < cur:
                bull, cur, ep, af = False, ep, lv[i], step
            elif hv[i] > ep:
                ep, af = hv[i], min(af + step, max_step)
        else:
            cur = max(cur, hv[i - 1], hv[max(i - 2, 0)])
            if hv[i] > cur:
                bull, cur, ep, af = True, ep, hv[i], step
            elif lv[i] < ep:
                ep, af = lv[i], min(af + step, max_step)
        sar[i] = cur
    return pd.Series(sar, index=h.index)


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Stationary features from OHLCV bars (scale-free across price drift).

    Includes the full voter panel: every indicator from the companion's
    25-indicator vote is recomputed per bar as a -1/0/+1 sign column
    (``sig_*``), plus ``vote_score`` — the literal vote consensus — so the
    ML/DL ensemble LEARNS which voters matter and when.
    """
    h, l, c = df["high"], df["low"], df["close"]
    vol = df["tick_volume"]
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = _rma(tr, 14).replace(0, np.nan)

    delta = c.diff()
    gain = _rma(delta.clip(lower=0), 14)
    loss = _rma(-delta.clip(upper=0), 14)
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    ll = l.rolling(14, min_periods=14).min()
    hh = h.rolling(14, min_periods=14).max()
    stoch_k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)

    macd = _ema(c, 12) - _ema(c, 26)
    macd_sig = macd.ewm(span=9, adjust=False, min_periods=9).mean()

    up = h.diff()
    down = -l.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_di = 100 * _rma(plus_dm, 14) / atr
    minus_di = 100 * _rma(minus_dm, 14) / atr
    di_diff = (_rma(plus_dm, 14) - _rma(minus_dm, 14)) / atr

    f = pd.DataFrame(index=df.index)
    f["ret_1"] = c.pct_change(1)
    f["ret_3"] = c.pct_change(3)
    f["ret_8"] = c.pct_change(8)
    f["ret_16"] = c.pct_change(16)
    f["rsi"] = rsi
    f["stoch_k"] = stoch_k
    f["stoch_d"] = stoch_k.rolling(3, min_periods=3).mean()
    f["macd_hist_atr"] = (macd - macd_sig) / atr
    f["d_ema9"] = (c - _ema(c, 9)) / atr
    f["d_ema21"] = (c - _ema(c, 21)) / atr
    f["d_ema50"] = (c - _ema(c, 50)) / atr
    f["di_diff"] = di_diff
    f["atr_pct"] = atr / c
    f["vol_z"] = (vol - vol.rolling(50).mean()) / vol.rolling(50).std(ddof=0)
    f["hour"] = df.index.hour
    f["dow"] = df.index.dayofweek

    # ── voter panel: each vote indicator as a per-bar -1/0/+1 sign ──────
    def _sign(cond_buy, cond_sell):
        return pd.Series(np.where(cond_buy, 1.0, np.where(cond_sell, -1.0, 0.0)),
                         index=df.index)

    sma20 = c.rolling(20, min_periods=20).mean()
    ema21 = _ema(c, 21)
    f["sig_rsi"] = _sign(rsi < 30, rsi > 70)
    f["sig_stoch"] = _sign(stoch_k < 20, stoch_k > 80)
    f["sig_macd"] = _sign(macd > macd_sig, macd < macd_sig)
    f["sig_sma"] = _sign(c > sma20, c < sma20)
    f["sig_ema"] = _sign(c > ema21, c < ema21)
    f["sig_dmi"] = _sign((plus_di > minus_di) & (plus_di > 25),
                         (minus_di > plus_di) & (minus_di > 25))

    tp = (h + l + c) / 3.0
    tp_sma = tp.rolling(20, min_periods=20).mean()
    tp_mad = tp.rolling(20, min_periods=20).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - tp_sma) / (0.015 * tp_mad.replace(0, np.nan))
    f["sig_cci"] = _sign(cci < -100, cci > 100)

    wr = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    f["sig_wr"] = _sign(wr < -80, wr > -20)

    roc = (c / c.shift(12) - 1.0) * 100.0
    f["sig_roc"] = _sign(roc > 0, roc < 0)
    f["sig_momentum"] = _sign(c - c.shift(10) > 0, c - c.shift(10) < 0)

    diff = c.diff()
    tsi_num = diff.ewm(span=25, adjust=False, min_periods=25).mean() \
        .ewm(span=13, adjust=False, min_periods=13).mean()
    tsi_den = diff.abs().ewm(span=25, adjust=False, min_periods=25).mean() \
        .ewm(span=13, adjust=False, min_periods=13).mean()
    tsi = 100 * tsi_num / tsi_den.replace(0, np.nan)
    f["sig_tsi"] = _sign(tsi > 25, tsi < -25)

    bb_mid = c.rolling(20, min_periods=20).mean()
    bb_sd = c.rolling(20, min_periods=20).std(ddof=0)
    f["sig_bb"] = _sign(c < bb_mid - 2 * bb_sd, c > bb_mid + 2 * bb_sd)

    rmf = tp * vol.fillna(0.0)
    pos_mf = rmf.where(tp > tp.shift(1), 0.0).rolling(14, min_periods=14).sum()
    neg_mf = rmf.where(tp < tp.shift(1), 0.0).rolling(14, min_periods=14).sum()
    mfi = 100 - 100 / (1 + pos_mf / neg_mf.replace(0, np.nan))
    f["sig_mfi"] = _sign(mfi < 20, mfi > 80)

    dc_hi = h.rolling(20, min_periods=20).max().shift(1)
    dc_lo = l.rolling(20, min_periods=20).min().shift(1)
    f["sig_donchian"] = _sign(c > dc_hi, c < dc_lo)
    pc_hi = c.rolling(20, min_periods=20).max().shift(1)
    pc_lo = c.rolling(20, min_periods=20).min().shift(1)
    f["sig_price_channel"] = _sign(c > pc_hi, c < pc_lo)

    kc_center = _ema(c, 20)
    f["sig_keltner"] = _sign(c > kc_center + 2 * atr, c < kc_center - 2 * atr)

    tr_sum = tr.rolling(14, min_periods=14).sum().replace(0, np.nan)
    vi_plus = (h - l.shift(1)).abs().rolling(14, min_periods=14).sum() / tr_sum
    vi_minus = (l - h.shift(1)).abs().rolling(14, min_periods=14).sum() / tr_sum
    f["sig_vortex"] = _sign(vi_plus > vi_minus, vi_minus > vi_plus)

    cmo_up = delta.clip(lower=0).rolling(14, min_periods=14).sum()
    cmo_dn = (-delta.clip(upper=0)).rolling(14, min_periods=14).sum()
    cmo = 100 * (cmo_up - cmo_dn) / (cmo_up + cmo_dn).replace(0, np.nan)
    f["sig_cmo"] = _sign(cmo <= -50, cmo >= 50)

    roc_sum = (c / c.shift(14) - 1.0) * 100.0 + (c / c.shift(11) - 1.0) * 100.0
    weights = np.arange(1, 11, dtype=float)
    coppock = roc_sum.rolling(10, min_periods=10).apply(
        lambda x: float((x * weights).sum() / weights.sum()), raw=True)
    f["sig_coppock"] = _sign(coppock.diff() > 0, coppock.diff() < 0)

    true_low = pd.concat([l, prev], axis=1).min(axis=1)
    true_high = pd.concat([h, prev], axis=1).max(axis=1)
    bp_uo = c - true_low
    tr_uo = true_high - true_low

    def _uo_avg(n):
        return bp_uo.rolling(n, min_periods=n).sum() \
            / tr_uo.rolling(n, min_periods=n).sum().replace(0, np.nan)

    uo = 100 * (4 * _uo_avg(7) + 2 * _uo_avg(14) + _uo_avg(28)) / 7
    f["sig_uo"] = _sign(uo <= 30, uo >= 70)

    ema13 = _ema(c, 13)
    bull_pw = h - ema13
    bear_pw = l - ema13
    ema_rising = ema13.diff() > 0
    f["sig_elder"] = _sign(
        ema_rising & (bear_pw < 0) & (bear_pw > bear_pw.shift(1)),
        (~ema_rising) & (bull_pw > 0) & (bull_pw < bull_pw.shift(1)))

    median_p = (h + l) / 2.0
    jaw = median_p.ewm(alpha=1 / 13, adjust=False, min_periods=13).mean().shift(8)
    teeth = median_p.ewm(alpha=1 / 8, adjust=False, min_periods=8).mean().shift(5)
    lips = median_p.ewm(alpha=1 / 5, adjust=False, min_periods=5).mean().shift(3)
    f["sig_gator"] = _sign((lips > teeth) & (teeth > jaw),
                           (lips < teeth) & (teeth < jaw))

    up_fr = ((h > h.shift(1)) & (h > h.shift(2))
             & (h > h.shift(-1)) & (h > h.shift(-2)))
    dn_fr = ((l < l.shift(1)) & (l < l.shift(2))
             & (l < l.shift(-1)) & (l < l.shift(-2)))
    # confirmed 2 bars later → shift(2) keeps it causal
    up_level = h.where(up_fr).shift(2).ffill()
    dn_level = l.where(dn_fr).shift(2).ffill()
    f["sig_fractal"] = _sign(c > up_level, c < dn_level)

    st_dir = _supertrend_dir(h, l, c)
    f["sig_supertrend"] = st_dir
    psar = _psar_series(h, l)
    f["sig_psar"] = _sign(c > psar, c < psar)

    obv = (np.sign(delta.fillna(0.0)) * vol.fillna(0.0)).cumsum()
    f["sig_obv"] = _sign(obv.diff() > 0, obv.diff() < 0)

    # The literal vote, as the model's eye sees it: mean of all voter signs
    sig_cols = [col for col in f.columns if col.startswith("sig_")]
    f["vote_score"] = f[sig_cols].mean(axis=1)

    # ── continuous indicator values (richer than the -1/0/+1 signs) ─────
    f["cci_n"] = cci / 100.0
    f["wr_n"] = (wr + 50.0) / 50.0          # center at 0
    f["mfi_n"] = (mfi - 50.0) / 50.0
    f["cmo_n"] = cmo / 100.0
    f["uo_n"] = (uo - 50.0) / 50.0
    f["tsi_n"] = tsi / 100.0
    f["roc_12"] = roc / 100.0
    f["vortex_diff"] = vi_plus - vi_minus
    # Bollinger %B and bandwidth (volatility squeeze/expansion regime)
    bb_width = (4 * bb_sd) / bb_mid.replace(0, np.nan)
    f["bb_pct_b"] = (c - (bb_mid - 2 * bb_sd)) / (4 * bb_sd).replace(0, np.nan)
    f["bb_width"] = bb_width
    # Channel positions in ATRs
    f["dc_pos"] = (c - (dc_hi + dc_lo) / 2.0) / atr
    f["kc_pos"] = (c - kc_center) / atr
    f["d_psar_atr"] = (c - psar) / atr
    # ADX trend strength + DI spread
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    f["adx"] = _rma(dx, 14)
    f["di_spread"] = (plus_di - minus_di) / 100.0
    # Volatility regime + EMA slope
    f["atr_regime"] = atr / _rma(tr, 50).replace(0, np.nan)
    f["ema21_slope"] = ema21.diff(3) / atr
    # Elder powers normalized
    f["bull_power_atr"] = bull_pw / atr
    f["bear_power_atr"] = bear_pw / atr
    # Candle anatomy (last-bar microstructure)
    rng_bar = (h - l).replace(0, np.nan)
    f["body_ratio"] = (c - df["open"]) / rng_bar
    f["upper_wick"] = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / rng_bar
    f["lower_wick"] = (pd.concat([c, df["open"]], axis=1).min(axis=1) - l) / rng_bar
    # Volume pressure
    f["vol_ratio"] = vol / vol.rolling(20, min_periods=20).mean().replace(0, np.nan)

    return f.replace([np.inf, -np.inf], np.nan)


def make_labels(df: pd.DataFrame, horizon: int = HORIZON_BARS,
                deadzone: float = DEADZONE_PCT) -> pd.Series:
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    y = pd.Series(np.nan, index=df.index, dtype=float)
    y[fwd > deadzone] = 1.0
    y[fwd < -deadzone] = 0.0
    return y


# ── training / evaluation ────────────────────────────────────────────────

def _usable_columns(X: pd.DataFrame) -> List[str]:
    """Columns with at least 2 distinct non-NaN values (sklearn binning
    crashes on constant or all-NaN features)."""
    cols = []
    for c in X.columns:
        s = X[c].dropna()
        if len(s) and s.nunique() > 1:
            cols.append(c)
    return cols


def _fit(X: pd.DataFrame, y: pd.Series, seed: int = 42):
    cols = _usable_columns(X)
    Xu = X[cols]
    gbm = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_depth=7, min_samples_leaf=35,
        l2_regularization=1.2, early_stopping=True, validation_fraction=0.15,
        random_state=seed,
    )
    mlp = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("net", MLPClassifier(
            hidden_layer_sizes=(128, 64, 32), activation="relu", alpha=5e-4,
            batch_size=128, learning_rate_init=8e-4, max_iter=350,
            early_stopping=True, n_iter_no_change=15, random_state=seed,
        )),
    ])
    et = ExtraTreesClassifier(
        n_estimators=250, max_depth=14, min_samples_leaf=25,
        max_features="sqrt", class_weight="balanced_subsample",
        random_state=seed, n_jobs=-1,
    )
    n = len(Xu)
    half_life = max(n / 4.0, 1.0)
    weights = np.power(0.5, (n - 1 - np.arange(n)) / half_life)
    weights *= n / weights.sum()
    try:
        gbm.fit(Xu, y, sample_weight=weights)
    except TypeError:
        gbm.fit(Xu, y)
    mlp.fit(Xu, y)
    try:
        et.fit(Xu, y, sample_weight=weights)
    except TypeError:
        et.fit(Xu, y)
    return gbm, mlp, et, cols


def _proba_up(gbm, mlp, et, cols: List[str], X: pd.DataFrame) -> Tuple[float, float, float]:
    """GBM + deep MLP + extra-trees — three-model soft vote."""
    Xu = X[cols]
    p_gbm = float(gbm.predict_proba(Xu)[:, list(gbm.classes_).index(1.0)][0])
    p_mlp = float(mlp.predict_proba(Xu)[:, list(mlp.classes_).index(1.0)][0])
    p_et = float(et.predict_proba(Xu)[:, list(et.classes_).index(1.0)][0])
    return p_gbm, p_mlp, p_et


def _walk_forward(X: pd.DataFrame, y: pd.Series,
                  threshold: float = CONFIDENCE_THRESHOLD) -> Dict[str, Any]:
    mask = y.notna()
    Xv, yv = X[mask], y[mask]
    n = len(Xv)
    if n < MIN_TRAIN_ROWS:
        return {"evaluated": False, "reason": f"{n} labeled rows (<{MIN_TRAIN_ROWS})"}
    edges = np.linspace(int(n * 0.5), n, WALK_FORWARD_FOLDS + 1, dtype=int)
    all_c: List[int] = []
    gated_c: List[int] = []
    gated_n = 0
    total = 0
    for i in range(WALK_FORWARD_FOLDS):
        tr_end, te_end = edges[i], edges[i + 1]
        if te_end - tr_end < 10:
            continue
        gbm, mlp, et, cols = _fit(Xv.iloc[:tr_end], yv.iloc[:tr_end])
        Xu_te = Xv.iloc[tr_end:te_end][cols]
        p_gbm = gbm.predict_proba(Xu_te)[:, list(gbm.classes_).index(1.0)]
        p_mlp = mlp.predict_proba(Xu_te)[:, list(mlp.classes_).index(1.0)]
        p_et = et.predict_proba(Xu_te)[:, list(et.classes_).index(1.0)]
        p = (p_gbm + p_mlp + p_et) / 3.0
        actual = yv.iloc[tr_end:te_end].to_numpy()
        correct = ((p >= 0.5).astype(float) == actual).astype(int)
        all_c.extend(correct.tolist())
        total += len(actual)
        gate = np.maximum(p, 1 - p) >= threshold
        gated_c.extend(correct[gate].tolist())
        gated_n += int(gate.sum())
    if not total:
        return {"evaluated": False, "reason": "no test rows"}
    return {
        "evaluated": True,
        "n_test": total,
        "accuracy": round(float(np.mean(all_c)), 4),
        "gated_accuracy": round(float(np.mean(gated_c)), 4) if gated_n else None,
        "gated_coverage": round(gated_n / total, 4),
        "confidence_threshold": threshold,
    }


def train_on_rates(rates, symbol: str = "ustech",
                   timeframe_minutes: int = 5) -> Dict[str, Any]:
    """Train the ensemble from raw MT5 rates; cache and return the bundle."""
    if not SKLEARN_AVAILABLE:
        return {"trained": False, "reason": "scikit-learn not installed"}
    df = rates_to_df(rates)
    if len(df) < MIN_TRAIN_ROWS:
        return {"trained": False, "reason": f"insufficient bars ({len(df)})"}
    X = make_features(df)
    y = make_labels(df)
    wf = _walk_forward(X, y)
    mask = y.notna()
    if int(mask.sum()) < MIN_TRAIN_ROWS:
        return {"trained": False, "reason": f"insufficient labeled rows ({int(mask.sum())})"}
    gbm, mlp, et, used_cols = _fit(X[mask], y[mask])
    bundle = {
        "trained": True,
        "gbm": gbm,
        "mlp": mlp,
        "et": et,
        "feature_columns": list(X.columns),
        "used_columns": used_cols,
        "walk_forward": wf,
        "n_labeled": int(mask.sum()),
        "trained_at": time.time(),
    }
    with _cache_lock:
        _cache[(symbol.lower(), timeframe_minutes)] = bundle
    _save_bundle_to_disk(symbol, timeframe_minutes, bundle)
    return bundle


def _mt5_timeframe(minutes: int):
    return {1: mt5.TIMEFRAME_M1, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15,
            30: mt5.TIMEFRAME_M30, 60: mt5.TIMEFRAME_H1}.get(minutes, mt5.TIMEFRAME_M5)


def _resolve_symbol(symbol: str) -> str:
    """MT5 symbol names are case-sensitive ('ustech' fetches nothing while
    'USTECH' works) — resolve to the broker's exact name."""
    if not MT5_AVAILABLE:
        return symbol
    try:
        for cand in (symbol, symbol.upper(), symbol.lower(), symbol.capitalize()):
            if mt5.symbol_info(cand) is not None:
                mt5.symbol_select(cand, True)
                return cand
    except Exception:
        pass
    return symbol


def _fetch_rates(symbol: str, timeframe_minutes: int, count: int):
    if not MT5_AVAILABLE:
        return None
    sym = _resolve_symbol(symbol)
    return mt5.copy_rates_from_pos(sym, _mt5_timeframe(timeframe_minutes), 0, count)


def fetch_recent_ticks(symbol: str, lookback_sec: int = TICK_LOOKBACK_SEC):
    """Live tick tape from MT5 — used to augment each 60s prediction."""
    if not MT5_AVAILABLE:
        return None
    sym = _resolve_symbol(symbol)
    utc_from = datetime.fromtimestamp(time.time() - lookback_sec, tz=timezone.utc)
    try:
        for flag in (mt5.COPY_TICKS_ALL, mt5.COPY_TICKS_INFO):
            ticks = mt5.copy_ticks_from(sym, utc_from, MAX_TICK_SAMPLE, flag)
            if ticks is not None and len(ticks) >= 20:
                return ticks
    except Exception:
        pass
    return None


def _tick_mid(tick) -> float:
    bid = float(tick["bid"])
    ask = float(tick["ask"])
    last = float(tick["last"]) if "last" in tick.dtype.names else 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last > 0:
        return last
    return max(bid, ask, 0.0)


def compute_tick_micro_features(ticks) -> Dict[str, Any]:
    """Microstructure from the live tick tape (velocity, vol, momentum)."""
    empty: Dict[str, Any] = {
        "ready": False, "tick_count": 0, "volatile_score": 0.0,
        "momentum_pts": 0.0, "tick_rate": 0.0, "uptick_ratio": 0.5,
        "realized_vol_pts": 0.0,
    }
    if ticks is None or len(ticks) < 20:
        return empty
    try:
        mids = np.array([_tick_mid(t) for t in ticks], dtype=float)
        times = np.array([int(t["time"]) for t in ticks], dtype=np.int64)
        valid = (mids > 0) & (times > 0)
        mids, times = mids[valid], times[valid]
        if len(mids) < 20:
            return empty

        rets = np.diff(mids)
        span = max(int(times[-1] - times[0]), 1)
        tick_rate = len(mids) / span
        realized_vol = float(np.std(rets)) if len(rets) > 2 else 0.0
        upticks = int((rets > 0).sum())
        downticks = int((rets < 0).sum())
        cast = upticks + downticks
        uptick_ratio = upticks / cast if cast else 0.5

        # Momentum: mid now vs ~60s ago (or earliest tick in window)
        cutoff = times[-1] - min(60, span)
        idx_old = int(np.searchsorted(times, cutoff, side="left"))
        idx_old = min(idx_old, len(mids) - 2)
        momentum_pts = float(mids[-1] - mids[idx_old])

        # Volatile score: tick vol + activity vs a quiet baseline (~0.15 pts std)
        vol_norm = min(1.0, realized_vol / 0.35)
        rate_norm = min(1.0, tick_rate / 8.0)
        volatile_score = float(min(1.0, 0.65 * vol_norm + 0.35 * rate_norm))

        return {
            "ready": True,
            "tick_count": int(len(mids)),
            "tick_rate": round(tick_rate, 2),
            "realized_vol_pts": round(realized_vol, 3),
            "uptick_ratio": round(uptick_ratio, 3),
            "momentum_pts": round(momentum_pts, 2),
            "volatile_score": round(volatile_score, 3),
            "span_sec": int(span),
        }
    except Exception:
        return empty


def _weighted_ensemble_p_up(p_gbm: float, p_mlp: float, p_et: float,
                            volatile: bool) -> Tuple[float, Dict[str, float]]:
    """Soft vote — DL gets extra weight; volatile sessions favour the DL leg."""
    if volatile:
        w = {"gbm": 0.18, "dl": 0.55, "et": 0.27}
    else:
        w = {"gbm": 0.25, "dl": 0.45, "et": 0.30}
    p_up = w["gbm"] * p_gbm + w["dl"] * p_mlp + w["et"] * p_et
    return p_up, w


def get_cached_bundle(symbol: str = "ustech",
                      timeframe_minutes: int = 5) -> Optional[Dict[str, Any]]:
    key = (symbol.lower(), timeframe_minutes)
    with _cache_lock:
        b = _cache.get(key)
    if b and b.get("trained") and time.time() - b["trained_at"] < RETRAIN_INTERVAL_SEC:
        return b
    # Cold start — try the model persisted by the previous app session
    if not SKLEARN_AVAILABLE:
        return None
    disk = _load_bundle_from_disk(symbol, timeframe_minutes)
    if disk and time.time() - disk.get("trained_at", 0) < RETRAIN_INTERVAL_SEC:
        with _cache_lock:
            _cache[key] = disk
        return disk
    return None


def is_training(symbol: str = "ustech", timeframe_minutes: int = 5) -> bool:
    with _training_lock:
        return (symbol.lower(), timeframe_minutes) in _training


def wait_for_model(symbol: str = "ustech", timeframe_minutes: int = 5,
                   timeout_sec: float = 90.0) -> Optional[Dict[str, Any]]:
    """Block until a trained model exists, training stops, or timeout.

    Used on the FIRST signal request so the AI's opinion comes from the
    ML/DL ensemble instead of instantly falling back to indicators while
    training is still running. Subsequent requests hit the cache (memory
    or disk) and never wait.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        bundle = get_cached_bundle(symbol, timeframe_minutes)
        if bundle:
            return bundle
        if not is_training(symbol, timeframe_minutes):
            return get_cached_bundle(symbol, timeframe_minutes)
        time.sleep(2.0)
    return get_cached_bundle(symbol, timeframe_minutes)


TRAIN_RETRY_ATTEMPTS = 3
TRAIN_RETRY_WAIT_SEC = 20


def ensure_trained_async(symbol: str = "ustech", timeframe_minutes: int = 5,
                         log_fn=None) -> bool:
    """Kick off background training if no fresh model exists. Never blocks.

    Retries when the broker hasn't finished loading bars yet (the usual
    cause of "insufficient bars" right after MT5 connect).
    Returns True if a fresh model is already available.
    """
    if get_cached_bundle(symbol, timeframe_minutes):
        return True
    if not (SKLEARN_AVAILABLE and MT5_AVAILABLE):
        return False
    key = (symbol.lower(), timeframe_minutes)
    with _training_lock:
        if key in _training:
            return False
        _training.add(key)

    def _run():
        try:
            for attempt in range(1, TRAIN_RETRY_ATTEMPTS + 1):
                if log_fn:
                    log_fn(f"🧠 ML training attempt {attempt}/{TRAIN_RETRY_ATTEMPTS} "
                           f"for {symbol} M{timeframe_minutes} (up to {TRAIN_BARS} bars)…")
                rates = _fetch_rates(symbol, timeframe_minutes, TRAIN_BARS)
                got = 0 if rates is None else len(rates)
                bundle = train_on_rates(rates, symbol, timeframe_minutes)
                if bundle.get("trained"):
                    wf = bundle.get("walk_forward") or {}
                    if log_fn:
                        log_fn(f"🧠 ML model READY for {symbol} M{timeframe_minutes} "
                               f"[GBM trees + MLP 64x32 deep net, soft-vote]: "
                               f"wf_acc={wf.get('accuracy')} gated={wf.get('gated_accuracy')} "
                               f"(n={bundle.get('n_labeled')})")
                    return
                reason = str(bundle.get("reason", ""))
                if log_fn:
                    log_fn(f"🧠 ML training attempt {attempt} failed: {reason} "
                           f"(MT5 returned {got} bars)")
                if "insufficient" not in reason.lower():
                    return  # non-recoverable (e.g. sklearn missing)
                # Bars likely still downloading from the broker — wait and retry
                time.sleep(TRAIN_RETRY_WAIT_SEC)
        except Exception as e:
            if log_fn:
                log_fn(f"🧠 ML training error: {e}")
        finally:
            with _training_lock:
                _training.discard(key)

    threading.Thread(target=_run, name=f"ml-train-{symbol}", daemon=True).start()
    return False


def get_ml_direction(symbol: str = "ustech", timeframe_minutes: int = 5,
                     rates=None, auto_train: bool = True,
                     trend_direction: Optional[str] = None) -> Dict[str, Any]:
    """Predict direction with the cached ensemble (non-blocking).

    Returns {ready, direction: buy|sell|neutral, probability, confidence,
    walk_forward}. ``ready=False`` means no fresh model — caller should use
    its fallback and call ``ensure_trained_async`` to warm the cache.

    ``trend_direction`` (buy/sell from closed-bar trend) prevents reversal
    entries: tick nudges and confident signals must align with the trend.
    """
    bundle = get_cached_bundle(symbol, timeframe_minutes)
    if not bundle:
        if auto_train:
            ensure_trained_async(symbol, timeframe_minutes)
        return {"ready": False, "direction": "neutral", "reason": "model not trained yet"}

    if rates is None:
        rates = _fetch_rates(symbol, timeframe_minutes, PREDICT_BARS)
    df = rates_to_df(rates)
    if len(df) < 60:
        return {"ready": False, "direction": "neutral", "reason": "insufficient live bars"}

    # Timing: predict from the last CLOSED bar. The forming bar's OHLC is
    # still changing — indicators computed on it flip mid-bar and degrade
    # accuracy. Training labels are built from closed bars, so prediction
    # must see the same kind of data.
    try:
        tf_sec = timeframe_minutes * 60
        if time.time() - df.index[-1].timestamp() < tf_sec:
            df = df.iloc[:-1]
    except Exception:
        pass
    if len(df) < 60:
        return {"ready": False, "direction": "neutral", "reason": "insufficient closed bars"}

    X = make_features(df)[bundle["feature_columns"]]
    cols = bundle.get("used_columns") or bundle["feature_columns"]
    Xu = X.iloc[[-1]][cols]
    try:
        vote_seen = float(X["vote_score"].iloc[-1])
    except Exception:
        vote_seen = None
    gbm, mlp, et = bundle["gbm"], bundle["mlp"], bundle.get("et")
    if et is None:
        p_gbm = float(gbm.predict_proba(Xu)[:, list(gbm.classes_).index(1.0)][0])
        p_mlp = float(mlp.predict_proba(Xu)[:, list(mlp.classes_).index(1.0)][0])
        p_et = (p_gbm + p_mlp) / 2.0
    else:
        p_gbm, p_mlp, p_et = _proba_up(gbm, mlp, et, cols, Xu)

    # Live tick tape — microstructure for this 60s scoring cycle
    tick_feats = compute_tick_micro_features(fetch_recent_ticks(symbol))
    try:
        atr_regime = float(X.iloc[-1].get("atr_regime", 1.0) or 1.0)
    except Exception:
        atr_regime = 1.0
    volatile = (
        atr_regime >= VOLATILE_ATR_REGIME
        or (tick_feats.get("ready") and tick_feats.get("volatile_score", 0) >= VOLATILE_TICK_SCORE)
    )

    p_up, ens_weights = _weighted_ensemble_p_up(p_gbm, p_mlp, p_et, volatile)
    p_dl = p_mlp

    # Tick momentum nudge — only when it agrees with the prevailing trend
    # (short bounces in a downtrend must not flip the signal to BUY).
    tick_nudge = 0.0
    counter_trend = False
    if tick_feats.get("ready"):
        mom = float(tick_feats.get("momentum_pts") or 0.0)
        mom_buy = mom > 0
        mom_sell = mom < 0
        trend = (trend_direction or "").strip().lower()
        mom_ok = (
            not trend
            or (trend == "buy" and mom_buy)
            or (trend == "sell" and mom_sell)
        )
        if abs(mom) >= 0.5 and mom_ok:
            tick_nudge = min(0.06, abs(mom) / 50.0)  # smaller nudge — trend is king
            if mom_buy:
                p_up = min(1.0, p_up + tick_nudge)
            else:
                p_up = max(0.0, p_up - tick_nudge)
        elif abs(mom) >= 0.5 and trend in ("buy", "sell"):
            counter_trend = True

    conf = max(p_up, 1.0 - p_up)
    lean = "buy" if p_up >= 0.5 else "sell"

    if trend_direction in ("buy", "sell") and lean != trend_direction:
        counter_trend = True

    threshold = CONFIDENCE_THRESHOLD
    live_stats = None
    if prediction_tracker is not None:
        try:
            threshold = prediction_tracker.effective_confidence_threshold(
                CONFIDENCE_THRESHOLD, symbol)
            live_stats = prediction_tracker.get_stats(symbol)
        except Exception:
            pass
    threshold_base = threshold
    # Volatile markets — relax gate only when aligned with trend (no reversal entries)
    if volatile and not counter_trend:
        threshold = max(0.52, threshold - VOLATILE_GATE_RELAX)
        if tick_feats.get("ready"):
            mom = float(tick_feats.get("momentum_pts") or 0.0)
            trend = (trend_direction or "").strip().lower()
            aligned = (
                not trend
                or (trend == "buy" and mom > 0 and lean == "buy")
                or (trend == "sell" and mom < 0 and lean == "sell")
            )
            if aligned:
                threshold = max(0.50, threshold - 0.02)
    direction = lean if conf >= threshold and not counter_trend else "neutral"

    # Journal this prediction so it can be verified against the actual
    # market move + TP/SL simulation (deduped per closed bar).
    if prediction_tracker is not None:
        try:
            prediction_tracker.record(
                symbol,
                bar_time=int(df.index[-1].timestamp()),
                price=float(df["close"].iloc[-1]),
                p_up=p_up, confidence=conf, lean=lean, direction=direction,
                horizon_min=HORIZON_BARS * timeframe_minutes,
                vote_score_input=vote_seen,
            )
        except Exception:
            pass

    return {
        "ready": True,
        "model": "GBM + MLP(128x64x32) + ExtraTrees, DL-weighted + tick tape",
        "direction": direction,
        "lean": lean,
        "probability": round(p_up, 4),
        "gbm_probability": round(p_gbm, 4),
        "dl_probability": round(p_dl, 4),
        "et_probability": round(p_et, 4),
        "ensemble_weights": ens_weights,
        "confidence": round(conf, 4),
        "confidence_threshold": threshold,
        "base_threshold": threshold_base,
        "volatile_regime": volatile,
        "atr_regime": round(atr_regime, 3),
        "tick_features": tick_feats,
        "tick_nudge": round(tick_nudge, 4),
        "counter_trend": counter_trend,
        "trend_direction": trend_direction,
        "vote_score_input": round(vote_seen, 3) if vote_seen is not None
                            and not np.isnan(vote_seen) else None,
        "live_stats": live_stats,
        "walk_forward": bundle.get("walk_forward"),
        "n_labeled": bundle.get("n_labeled"),
    }
