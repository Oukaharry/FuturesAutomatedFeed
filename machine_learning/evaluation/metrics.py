"""Evaluation metrics for trade ML models."""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


def classification_metrics(y_true, y_pred, y_prob: Optional[np.ndarray] = None) -> Dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    out: Dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "n": int(len(y_true)),
    }
    if y_prob is not None and len(np.unique(y_true)) > 1:
        try:
            out["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        except ValueError:
            out["roc_auc"] = None
    else:
        out["roc_auc"] = None
    return out


def trading_filter_metrics(
    y_true_pnl: np.ndarray,
    y_pred_win: np.ndarray,
) -> Dict[str, float]:
    """
    Simulate taking only trades the model predicts as wins.
    y_true_pnl: actual net PnL per trade.
    y_pred_win: 1 = model says take trade, 0 = skip.
    """
    pnl = np.asarray(y_true_pnl, dtype=float)
    take = np.asarray(y_pred_win, dtype=int) == 1
    n_take = int(take.sum())
    if n_take == 0:
        return {
            "trades_taken": 0,
            "net_pnl_taken": 0.0,
            "win_rate_taken": 0.0,
            "net_pnl_all": float(pnl.sum()),
        }
    taken = pnl[take]
    return {
        "trades_taken": n_take,
        "net_pnl_taken": float(taken.sum()),
        "win_rate_taken": float((taken > 0).mean() * 100),
        "net_pnl_all": float(pnl.sum()),
        "avg_pnl_taken": float(taken.mean()),
    }
