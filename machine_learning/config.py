"""Paths and defaults for ML artifacts."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ml"
TRADES_PARQUET = DATA_DIR / "trades.parquet"
TRADES_CSV = DATA_DIR / "trades.csv"
MODELS_DIR = DATA_DIR / "models"
REPORTS_DIR = ROOT / "reports" / "ml"

DEFAULT_MIN_TRADES_TRAIN = 30
DEFAULT_WALK_FORWARD_SPLITS = 5
DEFAULT_TEST_RATIO = 0.2
RANDOM_STATE = 42

# Feature columns used by sklearn pipeline (after engineering)
NUMERIC_FEATURES = [
    "hour",
    "dow",
    "volume",
    "hold_minutes",
    "rolling_win_rate_5",
    "rolling_win_rate_20",
    "rolling_net_pnl_5",
    "trades_last_24h",
    "is_buy",
]

CATEGORICAL_FEATURES = ["symbol"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def model_path_for_client(client_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
    return MODELS_DIR / f"{safe}_win_classifier.joblib"
