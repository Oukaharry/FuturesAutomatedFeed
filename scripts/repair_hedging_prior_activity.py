"""
Repair inflated hedging_review.actual_hedging_results / discrepancy when historical
closed accounts were wrongly included in the discrepancy formula.

Usage:
  python scripts/repair_hedging_prior_activity.py
  python scripts/repair_hedging_prior_activity.py Reece
  python scripts/repair_hedging_prior_activity.py --dry-run
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_env_path = os.path.join(ROOT, ".env")
if os.path.isfile(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from dashboard.database import get_all_clients, get_client_data, save_client_data
from utils.data_processor import hedging_discrepancy_is_stale, sync_hedging_review_discrepancy


def repair_client(client_id, dry_run=False):
    data = get_client_data(client_id) or {}
    stats = data.get("statistics") or {}
    hr = stats.get("hedging_review") or {}
    if not hedging_discrepancy_is_stale(stats, data.get("account")):
        return None

    before_actual = hr.get("actual_hedging_results")
    before_disc = hr.get("discrepancy")
    before_net = (stats.get("cashflow_inprogress") or {}).get("net_profit")

    sync_hedging_review_discrepancy(stats, account=data.get("account"))
    data["statistics"] = stats
    if not dry_run:
        save_client_data(client_id, data)

    return {
        "client_id": client_id,
        "before_actual": before_actual,
        "after_actual": hr.get("actual_hedging_results"),
        "before_discrepancy": before_disc,
        "after_discrepancy": hr.get("discrepancy"),
        "before_net": before_net,
        "after_net": (stats.get("cashflow_inprogress") or {}).get("net_profit"),
    }


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if args:
        client_ids = args
    else:
        client_ids = list((get_all_clients() or {}).keys())

    fixed = []
    for cid in client_ids:
        result = repair_client(cid, dry_run=dry_run)
        if result:
            fixed.append(result)

    mode = "DRY RUN" if dry_run else "REPAIRED"
    print(f"{mode}: {len(fixed)} client(s)")
    for row in fixed:
        print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
