"""
Set Aymeric's 7/21–8/15/2026 profit split to $6,324 (50% of $12,648.55 net).

Uses admin override tables (same as dashboard Profit Split tab edits).
Run from repo root with DATABASE_URL in .env:

    python scripts/fix_aymeric_profit_split.py
    python scripts/fix_aymeric_profit_split.py --dry-run

Production (after git pull + web reload for watermark/UI fixes):

    bash scripts/run_aymeric_profit_split_production.sh
    # or: .\\scripts\\run_aymeric_profit_split_production.ps1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Period ending 8/15/2026 (legacy window truncated at cutover)
PERIOD_FROM = "7/21/2026"
NET_PROFIT = 12648.55
PROFIT_SPLIT = 6324.0


def _find_aymeric_client_id():
    from dashboard.database import get_all_clients

    matches = []
    for cid, meta in (get_all_clients() or {}).items():
        name = (meta.get("name") or cid or "").strip()
        if "aymeric" in name.lower() or "aymeric" in cid.lower():
            matches.append((cid, name))
    return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    matches = _find_aymeric_client_id()
    if not matches:
        print("No client matching 'Aymeric' found.")
        sys.exit(1)
    if len(matches) > 1:
        exact = [m for m in matches if m[0].strip().lower() == "aymeric"]
        if exact:
            matches = exact
        else:
            print("Multiple matches — pick one:")
            for cid, name in matches:
                print(f"  {cid!r} ({name})")
            sys.exit(1)

    client_id, display = matches[0]
    print(f"Client: {display} ({client_id})")
    print(f"Period from_date: {PERIOD_FROM}")
    print(f"Net profit override: ${NET_PROFIT:,.2f}")
    print(f"Profit split override: ${PROFIT_SPLIT:,.0f}")

    from dashboard.watermark_service import (
        compute_waterlog_from_db,
        save_net_profit_override,
        save_profit_split_override,
    )
    from dashboard.database import get_client_data

    before = compute_waterlog_from_db(client_id)
    if before and before.get("periods"):
        for p in before["periods"]:
            if (p.get("from_date") or "").strip() == PERIOD_FROM:
                print(
                    "Before:",
                    f"low={p.get('low')}",
                    f"profit_split={p.get('profit_split')}",
                )
                break

    data = get_client_data(client_id) or {}
    stats_net = None
    try:
        from dashboard.watermark_service import canonical_client_stats_net

        stats_net = canonical_client_stats_net(data)
        if stats_net is not None:
            print(f"Current dashboard stats net (live): ${stats_net:,.2f}")
    except Exception:
        pass

    if args.dry_run:
        print("Dry run — no DB writes.")
        return

    ok_np = save_net_profit_override(client_id, PERIOD_FROM, NET_PROFIT)
    ok_ps = save_profit_split_override(client_id, PERIOD_FROM, PROFIT_SPLIT)
    if not (ok_np and ok_ps):
        print("Failed to save overrides.")
        sys.exit(1)

    after = compute_waterlog_from_db(client_id)
    if after and after.get("periods"):
        for p in after["periods"]:
            if (p.get("from_date") or "").strip() == PERIOD_FROM:
                print(
                    "After:",
                    f"low={p.get('low')}",
                    f"profit_split={p.get('profit_split')}",
                    f"override={p.get('profit_split_override')}",
                )
                break
    print("Done.")


if __name__ == "__main__":
    main()
