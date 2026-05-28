#!/usr/bin/env python3
"""
Soft-delete evaluation rows for a client by Prop Firm name.

This sets `ev["_deleted"] = True` for matching evaluation rows and saves ONLY the
updated `evaluations` array back to the DB. (No other client data is touched.)

Dry-run by default. Use --apply to persist changes (and write a JSON backup).

Usage:
  python scripts/delete_client_evaluations_by_prop_firm.py --client "Fallback" --prop-firm "My Funded Futures"
  python scripts/delete_client_evaluations_by_prop_firm.py --client "Fallback" --prop-firm "My Funded Futures" --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _norm(s: Any) -> str:
    return str(s or "").strip().lower().replace("_", " ").replace("-", " ")


def _backup_path(client_id: str, out_dir: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (client_id or "client"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, f"_backup_{safe}_evals_deleted_{ts}.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Soft-delete evaluation rows by Prop Firm.")
    ap.add_argument("--client", required=True, help="Exact client_id as stored in DB")
    ap.add_argument(
        "--prop-firm",
        action="append",
        required=True,
        help="Prop firm name to delete (repeat flag for multiple)",
    )
    ap.add_argument("--apply", action="store_true", help="Persist changes to DB (default: dry-run)")
    ap.add_argument("--backup-dir", default=".", help="Directory for backup JSON when using --apply")
    args = ap.parse_args()

    from dashboard.database import get_client_data, save_client_data

    client_id = str(args.client or "").strip()
    targets = {_norm(x) for x in (args.prop_firm or []) if str(x or "").strip()}
    if not client_id or not targets:
        print("Missing --client or --prop-firm")
        return 2

    data = get_client_data(client_id) or {}
    evals = data.get("evaluations") or []
    if not isinstance(evals, list):
        print(f"Client {client_id!r}: evaluations is not a list; aborting.")
        return 2

    changed = 0
    new_evals: List[Any] = []
    for i, ev in enumerate(evals):
        if not isinstance(ev, dict):
            new_evals.append(ev)
            continue
        pf = _norm(ev.get("Prop Firm"))
        if pf in targets and not ev.get("_deleted"):
            ev2 = dict(ev)
            ev2["_deleted"] = True
            new_evals.append(ev2)
            changed += 1
        else:
            new_evals.append(ev)

    print(f"Client: {client_id}")
    print(f"Target prop firms: {sorted(targets)}")
    print(f"Rows soft-deleted: {changed}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to save.")
        return 0

    os.makedirs(args.backup_dir, exist_ok=True)
    bp = _backup_path(client_id, args.backup_dir)
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(evals, f, indent=2, ensure_ascii=False)
    print(f"Backup written: {bp}")

    ok = save_client_data(client_id, {"evaluations": new_evals}, overwrite=False)
    if not ok:
        print("Save failed.")
        return 1

    print("Saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

