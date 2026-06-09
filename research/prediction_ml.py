"""Market forecast entry point — momentum windows from M1 (replaces opaque classifier)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from research.momentum_forecast import run_momentum_forecast


def run_market_pipeline(
    m1_bars: List[dict],
    *,
    active_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    M1 USTECH → momentum bias + forecast window (10m … 4h) in EAT.
    `active_df` kept for API compat; forecast is purely from M1.
    """
    _ = active_df
    fc = run_momentum_forecast(m1_bars)
    pred = fc.get("prediction") or {}
    state = fc.get("state") or {}

    return {
        "meta": fc.get("meta") or {},
        "features": pd.DataFrame(),
        "feature_names": [],
        "model": {
            "trained": pred.get("ready", False),
            "method": "momentum_forecast",
            "session_hours_eat": "02:00–20:00",
        },
        "prediction": pred,
        "backtest": fc.get("backtest") or {},
        "momentum": state,
        "forecast": fc,
    }
