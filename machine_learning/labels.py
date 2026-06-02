"""Label definitions for supervised learning."""
from __future__ import annotations

import pandas as pd


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add classification and regression targets from net_pnl."""
    out = df.copy()
    out["win"] = (out["net_pnl"] > 0).astype(int)
    out["loss"] = (out["net_pnl"] < 0).astype(int)
    out["y_pnl"] = out["net_pnl"].astype(float)
    return out
