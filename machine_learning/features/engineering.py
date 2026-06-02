"""Feature engineering on trade-level rows (no future leakage)."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from machine_learning.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def _add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["entry_time"] = pd.to_datetime(out["entry_time"])
    out["hour"] = out["entry_time"].dt.hour.astype(int)
    out["dow"] = out["entry_time"].dt.weekday.astype(int)
    out["is_buy"] = (out["direction"].str.upper() == "BUY").astype(int)
    return out


def _add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling stats use only prior trades (shifted)."""
    out = df.copy()
    out = out.sort_values("entry_time").reset_index(drop=True)

    out["win"] = (out["net_pnl"] > 0).astype(int)
    prior_win = out["win"].shift(1)
    prior_pnl = out["net_pnl"].shift(1)

    out["rolling_win_rate_5"] = prior_win.rolling(5, min_periods=1).mean().fillna(0.5)
    out["rolling_win_rate_20"] = prior_win.rolling(20, min_periods=1).mean().fillna(0.5)
    out["rolling_net_pnl_5"] = prior_pnl.rolling(5, min_periods=1).sum().fillna(0.0)

    trades_24h = []
    times = out["entry_time"].values
    for i in range(len(out)):
        if i == 0:
            trades_24h.append(0)
            continue
        t0 = times[i]
        cutoff = t0 - np.timedelta64(24, "h")
        count = int(((times[:i] >= cutoff) & (times[:i] < t0)).sum())
        trades_24h.append(count)
    out["trades_last_24h"] = trades_24h

    return out


def build_feature_matrix(
    df: pd.DataFrame,
    client_id: str | None = None,
) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Returns (X_ready_df with engineered cols, y_class, y_reg) sorted by entry_time.
    If client_id set, filter to that client first.
    """
    if df.empty:
        return df, pd.Series(dtype=int), pd.Series(dtype=float)

    work = df.copy()
    if client_id:
        work = work[work["client_id"] == client_id]
    if work.empty:
        return work, pd.Series(dtype=int), pd.Series(dtype=float)

    work = _add_time_features(work)
    work = _add_rolling_features(work)
    work["y_class"] = (work["net_pnl"] > 0).astype(int)
    work["y_reg"] = work["net_pnl"].astype(float)

    y_class = work["y_class"]
    y_reg = work["y_reg"]
    return work, y_class, y_reg


def get_feature_column_names() -> Tuple[List[str], List[str]]:
    return list(NUMERIC_FEATURES), list(CATEGORICAL_FEATURES)
