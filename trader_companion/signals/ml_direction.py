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
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

TRAIN_BARS = 20000            # ~70 days of M5
PREDICT_BARS = 300            # rolling-window warmup for the last row
HORIZON_BARS = 4              # 4 x M5 = 20 minutes ahead
DEADZONE_PCT = 0.0005         # |move| below 5 bps dropped from training
CONFIDENCE_THRESHOLD = 0.60
MIN_TRAIN_ROWS = 500
WALK_FORWARD_FOLDS = 4
RETRAIN_INTERVAL_SEC = 6 * 3600

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
                   ("gbm", "mlp", "feature_columns", "used_columns",
                    "walk_forward", "n_labeled", "trained_at")}
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


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Stationary features from OHLCV bars (scale-free across price drift)."""
    h, l, c = df["high"], df["low"], df["close"]
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
    f["vol_z"] = (df["tick_volume"] - df["tick_volume"].rolling(50).mean()) \
        / df["tick_volume"].rolling(50).std(ddof=0)
    f["hour"] = df.index.hour
    f["dow"] = df.index.dayofweek
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
        max_iter=250, learning_rate=0.06, max_depth=6, min_samples_leaf=40,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
        random_state=seed,
    )
    mlp = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("net", MLPClassifier(
            hidden_layer_sizes=(64, 32), activation="relu", alpha=1e-3,
            batch_size=128, learning_rate_init=1e-3, max_iter=250,
            early_stopping=True, n_iter_no_change=12, random_state=seed,
        )),
    ])
    gbm.fit(Xu, y)
    mlp.fit(Xu, y)
    return gbm, mlp, cols


def _proba_up(gbm, mlp, cols: List[str], X: pd.DataFrame) -> np.ndarray:
    Xu = X[cols]
    p1 = gbm.predict_proba(Xu)[:, list(gbm.classes_).index(1.0)]
    p2 = mlp.predict_proba(Xu)[:, list(mlp.classes_).index(1.0)]
    return (p1 + p2) / 2.0


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
        gbm, mlp, cols = _fit(Xv.iloc[:tr_end], yv.iloc[:tr_end])
        p = _proba_up(gbm, mlp, cols, Xv.iloc[tr_end:te_end])
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
    gbm, mlp, used_cols = _fit(X[mask], y[mask])
    bundle = {
        "trained": True,
        "gbm": gbm,
        "mlp": mlp,
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
                     rates=None) -> Dict[str, Any]:
    """Predict direction with the cached ensemble (non-blocking).

    Returns {ready, direction: buy|sell|neutral, probability, confidence,
    walk_forward}. ``ready=False`` means no fresh model — caller should use
    its fallback and call ``ensure_trained_async`` to warm the cache.
    """
    bundle = get_cached_bundle(symbol, timeframe_minutes)
    if not bundle:
        ensure_trained_async(symbol, timeframe_minutes)
        return {"ready": False, "direction": "neutral", "reason": "model not trained yet"}

    if rates is None:
        rates = _fetch_rates(symbol, timeframe_minutes, PREDICT_BARS)
    df = rates_to_df(rates)
    if len(df) < 60:
        return {"ready": False, "direction": "neutral", "reason": "insufficient live bars"}

    X = make_features(df)[bundle["feature_columns"]]
    cols = bundle.get("used_columns") or bundle["feature_columns"]
    Xu = X.iloc[[-1]][cols]
    gbm, mlp = bundle["gbm"], bundle["mlp"]
    p_gbm = float(gbm.predict_proba(Xu)[:, list(gbm.classes_).index(1.0)][0])
    p_dl = float(mlp.predict_proba(Xu)[:, list(mlp.classes_).index(1.0)][0])
    p_up = (p_gbm + p_dl) / 2.0
    conf = max(p_up, 1.0 - p_up)
    lean = "buy" if p_up >= 0.5 else "sell"
    direction = lean if conf >= CONFIDENCE_THRESHOLD else "neutral"
    return {
        "ready": True,
        "model": "GBM trees + MLP(64x32) deep net, soft-vote",
        "direction": direction,
        "lean": lean,
        "probability": round(p_up, 4),
        "gbm_probability": round(p_gbm, 4),
        "dl_probability": round(p_dl, 4),
        "confidence": round(conf, 4),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "walk_forward": bundle.get("walk_forward"),
        "n_labeled": bundle.get("n_labeled"),
    }
