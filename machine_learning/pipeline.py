"""End-to-end ML pipeline orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from machine_learning.config import (
    DEFAULT_MIN_TRADES_TRAIN,
    DEFAULT_WALK_FORWARD_SPLITS,
    REPORTS_DIR,
    ensure_dirs,
    model_path_for_client,
)
from machine_learning.export import export_trades_to_disk, load_trades_from_disk
from machine_learning.features.engineering import build_feature_matrix
from machine_learning.models.predict import load_model, predict_trades
from machine_learning.models.train import train_classifier
from machine_learning.report import render_ml_report
from machine_learning.trades.loader import load_client_trades_df, resolve_client_id


def export_trades(
    all_clients: bool = True,
    client_query: Optional[str] = None,
    client_ids: Optional[List[str]] = None,
) -> pd.DataFrame:
    ids = client_ids
    if client_query:
        ids = [resolve_client_id(client_query)]
    elif not all_clients and not ids:
        raise ValueError("Specify --all, a client name, or client_ids")
    return export_trades_to_disk(client_ids=ids)


def train_client_model(
    client_query: str,
    model_type: str = "random_forest",
    n_splits: int = DEFAULT_WALK_FORWARD_SPLITS,
    min_trades: int = DEFAULT_MIN_TRADES_TRAIN,
    from_disk: bool = False,
) -> Dict[str, Any]:
    client_id = resolve_client_id(client_query)
    ensure_dirs()

    if from_disk:
        raw = load_trades_from_disk()
        raw = raw[raw["client_id"] == client_id]
    else:
        raw = load_client_trades_df(client_id)

    if len(raw) < min_trades:
        raise ValueError(
            f"{client_id}: only {len(raw)} trades (need {min_trades}). "
            "Push full MT5 history from TradeOpss 1.6.5+ or lower --min-trades."
        )

    feat_df, _, _ = build_feature_matrix(raw, client_id=client_id)
    artifact = train_classifier(
        feat_df,
        client_id=client_id,
        model_type=model_type,
        n_splits=n_splits,
        save=True,
    )

    report_path = REPORTS_DIR / f"ml_report_{_safe_name(client_id)}.html"
    render_ml_report(client_id, feat_df, artifact.metrics, report_path)
    artifact.metrics["report_path"] = str(report_path)

    meta_path = model_path_for_client(client_id).with_suffix(".json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "client_id": client_id,
                "metrics": artifact.metrics,
                "model_type": model_type,
            },
            f,
            indent=2,
            default=str,
        )

    return artifact.metrics


def predict_client_trades(client_query: str) -> pd.DataFrame:
    client_id = resolve_client_id(client_query)
    raw = load_client_trades_df(client_id)
    feat_df, _, _ = build_feature_matrix(raw, client_id=client_id)
    artifact = load_model(client_id)
    return predict_trades(feat_df, artifact)


def run_full_pipeline(
    client_query: str,
    model_type: str = "random_forest",
) -> Dict[str, Any]:
    """Export all (if needed), train one client, write report."""
    ensure_dirs()
    try:
        load_trades_from_disk()
    except FileNotFoundError:
        export_trades(all_clients=True)
    return train_client_model(client_query, model_type=model_type, from_disk=True)


def _safe_name(client_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
