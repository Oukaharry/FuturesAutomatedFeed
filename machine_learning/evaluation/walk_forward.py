"""Time-ordered walk-forward cross-validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from machine_learning.evaluation.metrics import classification_metrics, trading_filter_metrics


@dataclass
class WalkForwardResult:
    folds: List[Dict[str, Any]] = field(default_factory=list)
    aggregate: Dict[str, Any] = field(default_factory=dict)


def walk_forward_splits(n_samples: int, n_splits: int) -> List[tuple]:
    """
    Expanding-window splits: train [0..train_end), test [train_end..test_end).
    """
    if n_samples < 10 or n_splits < 1:
        return []
    min_test = max(5, n_samples // (n_splits + 1))
    splits = []
    for i in range(1, n_splits + 1):
        test_end = min(n_samples, (i + 1) * min_test)
        train_end = test_end - min_test
        if train_end < min_test:
            continue
        if test_end <= train_end:
            continue
        splits.append((0, train_end, train_end, test_end))
    if not splits:
        mid = int(n_samples * 0.8)
        splits = [(0, mid, mid, n_samples)]
    return splits


def walk_forward_evaluate(
    X: pd.DataFrame,
    y: pd.Series,
    pnl: pd.Series,
    train_predict_fn: Callable[[pd.DataFrame, pd.Series, pd.DataFrame], tuple],
    n_splits: int = 5,
) -> WalkForwardResult:
    """
    train_predict_fn(X_train, y_train, X_test) -> (y_pred, y_prob or None)
    """
    n = len(X)
    splits = walk_forward_splits(n, n_splits)
    result = WalkForwardResult()
    accs, aucs, f1s = [], [], []
    pnl_taken, wr_taken = [], []

    for fold_i, (tr0, tr1, te0, te1) in enumerate(splits):
        X_train, y_train = X.iloc[tr0:tr1], y.iloc[tr0:tr1]
        X_test = X.iloc[te0:te1]
        y_test = y.iloc[te0:te1]
        pnl_test = pnl.iloc[te0:te1]

        if len(X_train) < 10 or len(X_test) < 3:
            continue

        y_pred, y_prob = train_predict_fn(X_train, y_train, X_test)
        cls = classification_metrics(y_test, y_pred, y_prob)
        trade = trading_filter_metrics(pnl_test.values, y_pred)

        fold = {
            "fold": fold_i + 1,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "classification": cls,
            "trading_filter": trade,
        }
        result.folds.append(fold)
        accs.append(cls["accuracy"])
        if cls.get("roc_auc") is not None:
            aucs.append(cls["roc_auc"])
        f1s.append(cls["f1"])
        pnl_taken.append(trade["net_pnl_taken"])
        wr_taken.append(trade["win_rate_taken"])

    result.aggregate = {
        "folds_run": len(result.folds),
        "mean_accuracy": float(np.mean(accs)) if accs else None,
        "mean_f1": float(np.mean(f1s)) if f1s else None,
        "mean_roc_auc": float(np.mean(aucs)) if aucs else None,
        "sum_pnl_filter": float(np.sum(pnl_taken)) if pnl_taken else None,
        "mean_win_rate_filter": float(np.mean(wr_taken)) if wr_taken else None,
    }
    return result
