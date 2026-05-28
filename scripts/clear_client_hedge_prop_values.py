#!/usr/bin/env python3
"""
Clear hedge / prop-day values for a single client (default: Fallback).

This script edits ONLY `clients_data.evaluations` for the target client:
  - Clears Hedge Result* fields (including funded *.1 variants)
  - Clears Hedge Net / Hedge Net.1
  - Clears Hedge Day* fields
  - Clears Prop Day* and Prop Progress* fields
  - Clears hidden Hedge Day date trackers (keys like "_Hedge Day 1 Date") if present

Dry-run by default. Use --apply to persist changes.

Usage:
  python scripts/clear_client_hedge_prop_values.py
  python scripts/clear_client_hedge_prop_values.py --client "Fallback" --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _is_blankish(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s in ("-", "--", "—", "–")


def _should_clear_key(key: str) -> bool:
    k = str(key or "")

    if k.startswith("Hedge Result"):
        return True
    if k in ("Hedge Net", "Hedge Net.1"):
        return True
    if k.startswith("Hedge Day"):
        return True
    if k.startswith("Prop Day"):
        return True
    if k.startswith("Prop Progress"):
        return True

    # Hidden farming date trackers used by some imports/engines.
    # Example keys: "_Hedge Day 1 Date", "_Hedge Day 12 Date"
    if k.startswith("_Hedge Day") and "Date" in k:
        return True

    return False


def _clear_eval_fields(ev: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Return (new_ev, cleared_count). Only touches hedge/prop-day keys.
    """
    if not isinstance(ev, dict):
        return ev, 0

    cleared = 0
    new_ev: Dict[str, Any] = dict(ev)
    for k in list(new_ev.keys()):
        if not _should_clear_key(k):
            continue
        if _is_blankish(new_ev.get(k)):
            continue
        new_ev[k] = ""
        cleared += 1
    return new_ev, cleared


def _backup_path(client_id: str, out_dir: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (client_id or "client"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, f"_backup_{safe}_evaluations_{ts}.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Clear hedge/prop-day values for one client.")
    ap.add_argument("--client", default="Fallback", help="Exact client_id as stored in DB (default: Fallback)")
    ap.add_argument("--apply", action="store_true", help="Persist changes to DB (default: dry-run)")
    ap.add_argument(
        "--backup-dir",
        default=".",
        help="Directory to write backup JSON when using --apply (default: current directory)",
    )
    args = ap.parse_args()

    from dashboard.database import get_client_data, save_client_data

    client_id = str(args.client or "").strip()
    if not client_id:
        print("Missing --client")
        return 2

    data = get_client_data(client_id) or {}
    evals = data.get("evaluations") or []
    if not isinstance(evals, list):
        print(f"Client {client_id!r}: evaluations is not a list; aborting.")
        return 2

    total_rows = len(evals)
    changed_rows = 0
    total_cleared = 0
    new_evals = []

    for i, ev in enumerate(evals):
        new_ev, cleared = _clear_eval_fields(ev if isinstance(ev, dict) else ev)
        new_evals.append(new_ev)
        if cleared:
            changed_rows += 1
            total_cleared += cleared

    print(f"Client: {client_id}")
    print(f"Evaluations: {total_rows}")
    print(f"Rows changed: {changed_rows}")
    print(f"Fields cleared: {total_cleared}")

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

