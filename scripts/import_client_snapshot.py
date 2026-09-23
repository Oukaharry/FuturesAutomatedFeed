#!/usr/bin/env python3
"""Import a JSON clients_data blob for one client (overwrite production row).

  python scripts/import_client_snapshot.py --client Harry --file scripts/backups/Harry_local_golden_snapshot.json --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass


def _summary(data: dict) -> dict:
    st = data.get("statistics") or {}
    cf = st.get("cashflow_inprogress") or {}
    return {
        "evaluations": len(data.get("evaluations") or []),
        "cf_payouts": cf.get("payouts"),
        "cf_hedge": cf.get("hedging_results"),
        "cf_net": cf.get("net_profit"),
        "mt5_balance": (data.get("account") or {}).get("balance"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir", default=os.path.join(ROOT, "scripts", "backups"))
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        payload = json.load(f)

    cid = str(args.client).strip()
    print("Import file summary:", json.dumps(_summary(payload), indent=2))

    if not args.apply:
        print("Dry-run. Re-run with --apply to overwrite DB.")
        return 0

    from dashboard.database import get_client_data, save_client_data

    before = get_client_data(cid) or {}
    os.makedirs(args.backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = os.path.join(args.backup_dir, f"_backup_{cid}_before_import_{ts}.json")
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(before, f, indent=2, ensure_ascii=False)
    print("Backed up current target to:", bp)

    ok = save_client_data(cid, payload, overwrite=True)
    print("Saved:", ok)
    if ok:
        after = get_client_data(cid) or {}
        print("After:", json.dumps(_summary(after), indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
