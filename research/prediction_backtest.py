"""Walk-forward backtest for market-direction ML (EAT session hours)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from research.market_signals import (
    EAT_SESSION_END_HOUR,
    EAT_SESSION_START_HOUR,
    best_entry_hours_from_hour_stats,
    forward_return_label,
    session_mask_eat,
)


def run_prediction_backtest(
    features: pd.DataFrame,
    feat_cols: List[str],
    model_result: Dict[str, Any],
    *,
    horizon_bars: Optional[int] = None,
    min_confidence: float = 0.55,
) -> Dict[str, Any]:
    """
    Expanding-window walk-forward on the holdout tail (last 30% of session bars).
    Reports direction accuracy and per-hour hit rates inside 02:00–20:00 EAT.
    """
    horizon = int(horizon_bars or model_result.get("horizon_bars") or 4)
    out: Dict[str, Any] = {
        "horizon_bars": horizon,
        "min_confidence": min_confidence,
        "session_eat": f"{EAT_SESSION_START_HOUR:02d}:00–{EAT_SESSION_END_HOUR:02d}:00",
    }

    if not model_result.get("trained") or features.empty or not feat_cols:
        out["note"] = model_result.get("reason") or "model not ready"
        return out

    work = features.copy()
    work["label"] = forward_return_label(work["close"], horizon)
    sess = session_mask_eat(work.index)
    work = work[sess & work["label"].notna()]
    if len(work) < 80:
        out["note"] = f"too few labeled session bars ({len(work)})"
        return out

    split = int(len(work) * 0.7)
    test = work.iloc[split:].copy()
    if len(test) < 30:
        out["note"] = "holdout too small"
        return out

    clf = model_result["model"]
    X = test[feat_cols].fillna(0)
    proba = clf.predict_proba(X)
    pred = clf.predict(X)
    conf = proba.max(axis=1)

    test = test.assign(
        pred=pred.astype(int),
        confidence=conf,
        correct=(pred.astype(int) == test["label"].astype(int)).astype(int),
    )

    # High-confidence subset (tradeable signals)
    sig = test[test["confidence"] >= min_confidence]
    n_sig = len(sig)
    hit = float(sig["correct"].mean()) if n_sig else 0.0

    # Simulated points P/L: +1 if correct direction, -1 if wrong (no sizing)
    sig = sig.copy()
    sig["sim_pnl"] = np.where(sig["correct"] == 1, 1.0, -1.0)
    cum = sig["sim_pnl"].cumsum() if n_sig else pd.Series(dtype=float)

    hours_eat = test.index.tz_convert("Africa/Nairobi").hour
    hour_rows: List[dict] = []
    for h in range(EAT_SESSION_START_HOUR, EAT_SESSION_END_HOUR + 1):
        mask = (hours_eat == h) & (test["confidence"] >= min_confidence)
        sub = test[mask]
        if len(sub) < 3:
            continue
        hour_rows.append(
            {
                "hour": h,
                "n": int(len(sub)),
                "hit_rate": round(float(sub["correct"].mean()), 4),
                "avg_conf": round(float(sub["confidence"].mean()), 4),
            }
        )

    best_hours = best_entry_hours_from_hour_stats(hour_rows, top_n=3)

    out.update(
        {
            "n_holdout_bars": len(test),
            "n_signals": n_sig,
            "hit_rate_all": round(float(test["correct"].mean()), 4),
            "hit_rate_confident": round(hit, 4),
            "avg_confidence": round(float(test["confidence"].mean()), 4),
            "simulated_trades": n_sig,
            "simulated_win_rate_pct": round(hit * 100, 2) if n_sig else 0.0,
            "simulated_net_score": int(sig["sim_pnl"].sum()) if n_sig else 0,
            "max_sim_drawdown": int((cum - cum.cummax()).min()) if len(cum) > 1 else 0,
            "hour_stats": hour_rows,
            "best_entry_hours": best_hours,
            "buy_signals": int((sig["pred"] == 1).sum()) if n_sig else 0,
            "sell_signals": int((sig["pred"] == 0).sum()) if n_sig else 0,
        }
    )
    return out
