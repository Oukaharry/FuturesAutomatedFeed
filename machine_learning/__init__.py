"""
TradeOpss machine learning: MT5 trade history → features → walk-forward models.

Usage (from project root):
    python -m machine_learning.cli export --all
    python -m machine_learning.cli train Aaron
    python -m machine_learning.cli report Aaron
"""

__version__ = "0.1.0"

from machine_learning.pipeline import export_trades, train_client_model, run_full_pipeline

__all__ = [
    "__version__",
    "export_trades",
    "train_client_model",
    "run_full_pipeline",
]
