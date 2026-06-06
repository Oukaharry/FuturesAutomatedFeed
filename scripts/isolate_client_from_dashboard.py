#!/usr/bin/env python3
"""
Clear hedge/MT5 dashboard data for one client and mark them push-blocked.

Steps:
  1. scripts/clear_client_hedge_prop_values.py  — blank Hedge Result*, Hedge Day*, etc.
  2. scripts/reset_client_mt5_stats_context.py — zero MT5 totals + hedging_review
  3. Set identity.push_blocked=true (companion pushes rejected once push_policy is deployed)

Dry-run by default.

Usage:
  python scripts/isolate_client_from_dashboard.py --client Fallback
  python scripts/isolate_client_from_dashboard.py --client Fallback --apply --backup-dir ~/backups
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _run_step(script: str, client_id: str, apply: bool, backup_dir: str, extra: list[str] | None = None) -> int:
    cmd = [
        sys.executable,
        os.path.join(ROOT, script),
        "--client",
        client_id,
    ]
    if apply:
        cmd.extend(["--apply", "--backup-dir", backup_dir])
    if extra:
        cmd.extend(extra)
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    return int(result.returncode or 0)


def _set_push_blocked(client_id: str, apply: bool) -> int:
    from dashboard.database import get_client_data, save_client_data

    data = get_client_data(client_id) or {}
    if not data:
        print(f"Client {client_id!r}: not found.")
        return 2

    identity = dict(data.get("identity") or {})
    identity["push_blocked"] = True
    identity["push_blocked_reason"] = "Isolated from dashboard MT5 pushes (hedge test account)"
    identity["push_blocked_at"] = datetime.now(timezone.utc).isoformat()

    print(f"\n>>> identity.push_blocked = True for {client_id!r}")
    if not apply:
        print("Dry-run only (identity not saved).")
        return 0

    ok = save_client_data(client_id, {"identity": identity}, overwrite=False)
    if not ok:
        print("Failed to save identity.push_blocked.")
        return 1
    print("Saved identity.push_blocked.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Clear hedge data and block dashboard pushes for one client.")
    ap.add_argument("--client", default="Fallback", help="Exact client_id in DB (default: Fallback)")
    ap.add_argument("--apply", action="store_true", help="Persist changes (default: dry-run)")
    ap.add_argument("--backup-dir", default=".", help="Backup directory for child scripts when using --apply")
    ap.add_argument(
        "--zero-fees",
        action="store_true",
        help="Also pass --zero-fees to reset_client_mt5_stats_context.py",
    )
    args = ap.parse_args()

    client_id = str(args.client or "").strip()
    if not client_id:
        print("Missing --client")
        return 2

    backup_dir = os.path.abspath(args.backup_dir)
    extra = ["--zero-fees"] if args.zero_fees else []

    print(f"Client: {client_id}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    rc = _run_step("scripts/clear_client_hedge_prop_values.py", client_id, args.apply, backup_dir)
    if rc:
        return rc

    rc = _run_step("scripts/reset_client_mt5_stats_context.py", client_id, args.apply, backup_dir, extra)
    if rc:
        return rc

    rc = _set_push_blocked(client_id, args.apply)
    if rc:
        return rc

    if args.apply:
        print("\nDone. Ensure dashboard/push_policy.py is deployed so pushes stay blocked.")
    else:
        print("\nDry-run complete. Re-run with --apply to persist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
