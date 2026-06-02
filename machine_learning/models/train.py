"""Train sklearn pipelines on trade features."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from machine_learning.config import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    RANDOM_STATE,
    model_path_for_client,
)
from machine_learning.evaluation.walk_forward import walk_forward_evaluate


@dataclass
class TrainedModel:
    client_id: str
    pipeline: Any
    feature_df_columns: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    walk_forward: Dict[str, Any] = field(default_factory=dict)
    model_type: str = "random_forest"


def _make_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    try:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse=False)
    cat_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("ohe", ohe),
    ])
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC_FEATURES),
            ("cat", cat_pipe, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )


def _build_classifier(model_type: str) -> Any:
    if model_type == "logistic":
        return LogisticRegression(max_iter=2000, random_state=RANDOM_STATE, class_weight="balanced")
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=3,
        random_state=RANDOM_STATE,
        class_weight="balanced",
        n_jobs=-1,
    )


def _select_xy(feature_df: pd.DataFrame) -> tuple:
    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    missing = [c for c in cols if c not in feature_df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    X = feature_df[cols].copy()
    y = feature_df["y_class"]
    pnl = feature_df["net_pnl"]
    return X, y, pnl


def train_classifier(
    feature_df: pd.DataFrame,
    client_id: str,
    model_type: str = "random_forest",
    n_splits: int = 5,
    save: bool = True,
) -> TrainedModel:
    if len(feature_df) < 30:
        raise ValueError(
            f"Need at least 30 trades to train (have {len(feature_df)}). "
            "Export more history or wait for more MT5 pushes."
        )

    X, y, pnl = _select_xy(feature_df)
    clf = _build_classifier(model_type)
    pipe = Pipeline([
        ("prep", _make_preprocessor()),
        ("clf", clf),
    ])

    def _fit_predict(X_tr, y_tr, X_te):
        pipe.fit(X_tr, y_tr)
        pred = pipe.predict(X_te)
        prob = None
        if hasattr(pipe, "predict_proba"):
            prob = pipe.predict_proba(X_te)[:, 1]
        return pred, prob

    wf = walk_forward_evaluate(X, y, pnl, _fit_predict, n_splits=n_splits)

    pipe.fit(X, y)
    train_pred = pipe.predict(X)
    train_prob = pipe.predict_proba(X)[:, 1] if hasattr(pipe, "predict_proba") else None

    from machine_learning.evaluation.metrics import classification_metrics

    metrics = {
        "in_sample": classification_metrics(y, train_pred, train_prob),
        "walk_forward": wf.aggregate,
        "folds": wf.folds,
        "n_trades": len(feature_df),
        "baseline_win_rate": float(y.mean() * 100),
    }

    importances = None
    if model_type == "random_forest" and hasattr(pipe.named_steps["clf"], "feature_importances_"):
        try:
            cat_names = pipe.named_steps["prep"].get_feature_names_out()
            imp = pipe.named_steps["clf"].feature_importances_
            pairs = sorted(zip(cat_names, imp), key=lambda x: -x[1])[:15]
            importances = [{"feature": str(a), "importance": float(b)} for a, b in pairs]
        except Exception:
            importances = None
    metrics["feature_importances"] = importances

    artifact = TrainedModel(
        client_id=client_id,
        pipeline=pipe,
        feature_df_columns=list(feature_df.columns),
        metrics=metrics,
        walk_forward=wf.aggregate,
        model_type=model_type,
    )

    if save:
        path = model_path_for_client(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "client_id": client_id,
                "pipeline": pipe,
                "metrics": metrics,
                "model_type": model_type,
            },
            path,
        )
        metrics["model_path"] = str(path)

    return artifact
