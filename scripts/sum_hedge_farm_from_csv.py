#!/usr/bin/env python3
"""
Sum hedging + farming components from a dashboard-style evaluations CSV.

Computes:
  - eval_hedge: sum(Hedge Result 1..5)
  - funded_core_hedge: sum(Hedge Result 1.1..5.1)
  - farming_hr: sum(Hedge Result 6..7)
  - hedge_days: sum(Hedge Day 1..50) (will use whichever exist in the CSV)
  - farming_total: Farming Net if present for row else (farming_hr + hedge_days)
  - in_progress_total_hedge: eval_hedge + funded_core_hedge

Usage:
  python scripts/sum_hedge_farm_from_csv.py "C:\\path\\to\\evaluations.csv"
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from typing import Dict, List


def parse_currency(val) -> float:
    if val is None:
        return 0.0
    s = str(val)
    s = (
        s.replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("\u00a0", "")  # NBSP
        .replace("\u202f", "")  # NNBSP
        .strip()
    )
    if not s or s == "-" or s.lower() == "nan":
        return 0.0
    # (123.45) → -123.45
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        s = "-" + s[1:-1].strip()
    # Strip thousands commas; keep dot decimals
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    args = ap.parse_args()

    path = args.csv_path
    if not os.path.exists(path):
        raise SystemExit(f"File not found: {path}")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        fieldnames = r.fieldnames or []

        p1_cols = [f"Hedge Result {i}" for i in range(1, 6)]
        fd_cols = [f"Hedge Result {i}.1" for i in range(1, 6)]
        farm_hr_cols = ["Hedge Result 6", "Hedge Result 7"]

        # Hedge day columns present (some exports have 34; some have 50)
        hedge_day_cols: List[str] = []
        for i in range(1, 51):
            c = f"Hedge Day {i}"
            if c in fieldnames:
                hedge_day_cols.append(c)

        if not hedge_day_cols:
            # fallback: discover any "Hedge Day N"
            for c in fieldnames:
                m = re.match(r"^Hedge Day (\d+)$", c)
                if m:
                    hedge_day_cols.append(c)

        totals: Dict[str, float] = {
            "eval_hedge": 0.0,
            "funded_core_hedge": 0.0,
            "farming_hr": 0.0,
            "hedge_days": 0.0,
            "farming_total": 0.0,
            "in_progress_total_hedge": 0.0,
        }

        rows = 0
        for row in r:
            rows += 1
            p1 = sum(parse_currency(row.get(c)) for c in p1_cols)
            fd = sum(parse_currency(row.get(c)) for c in fd_cols)
            farm_hr = sum(parse_currency(row.get(c)) for c in farm_hr_cols)
            hd = sum(parse_currency(row.get(c)) for c in hedge_day_cols)

            farming_net_raw = row.get("Farming Net")
            farming_net_set = farming_net_raw is not None and str(farming_net_raw).strip() not in ("", "-")
            farm_total = parse_currency(farming_net_raw) if farming_net_set else (farm_hr + hd)

            totals["eval_hedge"] += p1
            totals["funded_core_hedge"] += fd
            totals["farming_hr"] += farm_hr
            totals["hedge_days"] += hd
            totals["farming_total"] += farm_total
            totals["in_progress_total_hedge"] += (p1 + fd)

    def money(x: float) -> str:
        return f"{x:,.2f}"

    print(f"Rows: {rows}")
    print(f"Eval hedge (HR 1-5): {money(totals['eval_hedge'])}")
    print(f"Funded core hedge (HR 1.1-5.1): {money(totals['funded_core_hedge'])}")
    print(f"Total hedge (eval + funded core): {money(totals['in_progress_total_hedge'])}")
    print(f"Farming HR (HR 6-7): {money(totals['farming_hr'])}")
    print(f"Hedge Days total ({len(hedge_day_cols)} cols): {money(totals['hedge_days'])}")
    print(f"Farming total (Farming Net override else HR6-7+HedgeDays): {money(totals['farming_total'])}")


if __name__ == "__main__":
    main()

