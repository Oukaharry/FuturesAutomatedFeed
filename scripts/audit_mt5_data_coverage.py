#!/usr/bin/env python3
"""List MT5 deal coverage per client from clients_data."""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--production", action="store_true", help="SSH tunnel to production DB")
    args = ap.parse_args()

    from research.db_source import configure_source, run_with_production
    from research.trade_dataset import coverage_report

    if args.production:
        with run_with_production():
            df = coverage_report()
    else:
        configure_source()
        df = coverage_report()

    has = df[df["round_trips"] > 0].sort_values("round_trips", ascending=False)
    empty = df[df["round_trips"] == 0]

    print(f"Clients: {len(df)}  with trades: {len(has)}  without: {len(empty)}")
    print(f"Raw deals: {int(df['raw_deals'].sum())}  Round trips: {int(df['round_trips'].sum())}\n")
    print("Top 25 by round trips:")
    cols = ["client_id", "raw_deals", "round_trips", "parse_rate_pct", "total_net_pnl", "last_close"]
    print(has[cols].head(25).to_string(index=False))

    out = os.path.join(_ROOT, "research", "reports", "coverage.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
