"""Export trade-level dataset to disk."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from machine_learning.config import TRADES_CSV, TRADES_PARQUET, ensure_dirs
from machine_learning.labels import add_labels
from machine_learning.trades.loader import load_all_trades_df, list_client_ids


def export_trades_to_disk(
    output_parquet: Optional[Path] = None,
    output_csv: Optional[Path] = None,
    client_ids: Optional[List[str]] = None,
) -> pd.DataFrame:
    ensure_dirs()
    df = load_all_trades_df(client_ids)
    if df.empty:
        raise RuntimeError("No trades exported. Ensure clients have MT5 deals in clients_data.")

    df = add_labels(df)
    pq = output_parquet or TRADES_PARQUET
    csv = output_csv or TRADES_CSV
    pq.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(csv, index=False)
    try:
        df.to_parquet(pq, index=False)
    except Exception as exc:
        print(f"[ml] parquet skipped ({exc}); CSV written to {csv}")

    return df


def load_trades_from_disk(parquet_path: Optional[Path] = None) -> pd.DataFrame:
    pq = parquet_path or TRADES_PARQUET
    if pq.is_file():
        return pd.read_parquet(pq)
    if TRADES_CSV.is_file():
        return pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    raise FileNotFoundError(
        f"No dataset at {pq} or {TRADES_CSV}. Run: python -m machine_learning.cli export --all"
    )
