"""Load saved models and score trades."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import pandas as pd

from machine_learning.config import NUMERIC_FEATURES, CATEGORICAL_FEATURES, model_path_for_client
from machine_learning.features.engineering import build_feature_matrix


def load_model(client_id: str, path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or model_path_for_client(client_id)
    if not p.is_file():
        raise FileNotFoundError(f"No model at {p}. Run: python -m machine_learning.cli train {client_id}")
    return joblib.load(p)


def predict_trades(feature_df: pd.DataFrame, artifact: Dict[str, Any]) -> pd.DataFrame:
    pipe = artifact["pipeline"]
    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X = feature_df[cols]
    out = feature_df.copy()
    out["pred_win"] = pipe.predict(X)
    if hasattr(pipe, "predict_proba"):
        out["pred_win_prob"] = pipe.predict_proba(X)[:, 1]
    else:
        out["pred_win_prob"] = out["pred_win"].astype(float)
    out["pred_take"] = out["pred_win"] == 1
    return out
