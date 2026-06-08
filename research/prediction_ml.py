"""Market-direction classifier from M1 OHLC (multi-timeframe features)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from research.market_signals import (
    BASE_TIMEFRAME,
    EAT_SESSION_END_HOUR,
    EAT_SESSION_START_HOUR,
    bars_list_to_m1_df,
    build_multi_timeframe_features,
    format_entry_window,
    forward_return_label,
    session_mask_eat,
)

DEFAULT_HORIZON_BARS = 4  # 4 × 15m = 1 hour forward
DEFAULT_MIN_TRAIN = 300
DEFAULT_MIN_CONFIDENCE = 0.55


def _min_train() -> int:
    try:
        return max(100, int(os.environ.get("ML_MARKET_MIN_TRAIN", str(DEFAULT_MIN_TRAIN))))
    except ValueError:
        return DEFAULT_MIN_TRAIN


def _horizon_bars() -> int:
    try:
        return max(1, int(os.environ.get("ML_MARKET_HORIZON_BARS", str(DEFAULT_HORIZON_BARS))))
    except ValueError:
        return DEFAULT_HORIZON_BARS


def _min_confidence() -> float:
    try:
        return float(os.environ.get("ML_MARKET_MIN_CONFIDENCE", str(DEFAULT_MIN_CONFIDENCE)))
    except ValueError:
        return DEFAULT_MIN_CONFIDENCE


def train_market_classifier(
    features: pd.DataFrame,
    feat_cols: List[str],
    *,
    horizon_bars: Optional[int] = None,
    min_train: Optional[int] = None,
) -> Dict[str, Any]:
    """Time-ordered train/holdout on 15m bars inside EAT session."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import accuracy_score, classification_report

    horizon = horizon_bars if horizon_bars is not None else _horizon_bars()
    min_train_n = min_train if min_train is not None else _min_train()
    result: Dict[str, Any] = {
        "trained": False,
        "horizon_bars": horizon,
        "base_timeframe": BASE_TIMEFRAME,
        "min_confidence": _min_confidence(),
        "session_hours_eat": f"{EAT_SESSION_START_HOUR:02d}:00–{EAT_SESSION_END_HOUR:02d}:00",
    }

    if features.empty or not feat_cols or "close" not in features.columns:
        result["reason"] = "insufficient M1 / resampled bars"
        return result

    work = features.copy()
    work["label"] = forward_return_label(work["close"], horizon)
    sess = session_mask_eat(work.index)
    work = work[sess & work["label"].notna()]

    if len(work) < min_train_n:
        result["reason"] = f"need {min_train_n}+ labeled 15m bars in session, have {len(work)}"
        result["n_labeled"] = len(work)
        return result

    split = int(len(work) * 0.7)
    if split < min_train_n // 2:
        result["reason"] = "train split too small"
        return result

    train_df = work.iloc[:split]
    test_df = work.iloc[split:]
    X_train = train_df[feat_cols].fillna(0)
    y_train = train_df["label"].astype(int)
    X_test = test_df[feat_cols].fillna(0)
    y_test = test_df["label"].astype(int)

    clf = GradientBoostingClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.06,
        min_samples_leaf=40,
        subsample=0.85,
        random_state=42,
    )
    clf.fit(X_train, y_train)
    pred_test = clf.predict(X_test)
    acc = float(accuracy_score(y_test, pred_test)) if len(y_test) else 0.0

    result.update(
        {
            "trained": True,
            "model": clf,
            "feature_names": list(feat_cols),
            "n_labeled": len(work),
            "n_train": len(train_df),
            "n_test": len(test_df),
            "accuracy_test": round(acc, 4),
            "report": classification_report(y_test, pred_test, target_names=["SELL", "BUY"], zero_division=0),
            "reason": "",
        }
    )
    return result


def predict_latest(
    model_result: Dict[str, Any],
    features: pd.DataFrame,
    feat_cols: List[str],
) -> Dict[str, Any]:
    """Live signal from the most recent complete 15m bar."""
    out: Dict[str, Any] = {
        "trained": bool(model_result.get("trained")),
        "bias": "—",
        "confidence": 0.0,
        "min_confidence": model_result.get("min_confidence", _min_confidence()),
        "bar_time": None,
        "in_session": False,
    }
    if not model_result.get("trained") or features.empty:
        out["reason"] = model_result.get("reason") or "model not trained"
        return out

    clf = model_result.get("model")
    if clf is None:
        out["reason"] = "no model"
        return out

    sess = session_mask_eat(features.index)
    eligible = features[sess]
    if eligible.empty:
        eligible = features
    row = eligible.iloc[[-1]]
    X = row[feat_cols].fillna(0)
    pred = int(clf.predict(X)[0])
    proba = clf.predict_proba(X)[0]
    conf = float(max(proba))
    bias = "BUY" if pred == 1 else "SELL"

    ts = row.index[-1]
    hour_eat = int(ts.tz_convert("Africa/Nairobi").hour)
    out.update(
        {
            "bias": bias,
            "confidence": round(conf, 4),
            "bar_time": ts.isoformat(),
            "in_session": EAT_SESSION_START_HOUR <= hour_eat <= EAT_SESSION_END_HOUR,
            "hour_eat": hour_eat,
            "prob_buy": round(float(proba[1]), 4),
            "prob_sell": round(float(proba[0]), 4),
        }
    )
    return out


def run_market_pipeline(m1_bars: List[dict]) -> Dict[str, Any]:
    """
    Full market ML path: M1 → multi-TF features → train → live prediction.
  Backtest is attached by prediction_backtest.run_prediction_backtest when imported.
    """
    m1 = bars_list_to_m1_df(m1_bars)
    meta: Dict[str, Any] = {
        "m1_bars": len(m1),
        "base_timeframe": BASE_TIMEFRAME,
    }
    if m1.empty:
        return {
            "meta": meta,
            "features": pd.DataFrame(),
            "feature_names": [],
            "model": {"trained": False, "reason": "no M1 bars"},
            "prediction": {"trained": False, "bias": "—", "reason": "no M1 bars"},
            "backtest": {},
        }

    features, feat_cols = build_multi_timeframe_features(m1)
    meta["feature_rows"] = len(features)
    meta["feature_cols"] = len(feat_cols)

    model = train_market_classifier(features, feat_cols)
    prediction = predict_latest(model, features, feat_cols)

    backtest: Dict[str, Any] = {}
    try:
        from research.prediction_backtest import run_prediction_backtest

        backtest = run_prediction_backtest(features, feat_cols, model)
        best_hours = backtest.get("best_entry_hours") or []
        prediction["best_entry_window"] = format_entry_window(best_hours)
        prediction["best_entry_hours"] = best_hours
    except Exception as e:
        backtest = {"error": str(e)}

    return {
        "meta": meta,
        "features": features,
        "feature_names": feat_cols,
        "model": model,
        "prediction": prediction,
        "backtest": backtest,
    }
