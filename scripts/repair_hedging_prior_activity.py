"""
Repair stale hedging_review.actual_hedging_results / discrepancy when prior MT5
PnL was saved but stats were not recalculated.

Usage:
  python scripts/repair_hedging_prior_activity.py
  python scripts/repair_hedging_prior_activity.py "Oliver MFFU KYC (Lau)"
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
from utils.data_processor import compute_live_actual_hedging, sync_hedging_review_discrepancy


def _has_prior_activity(hr):
    if not hr:
        return False
    if hr.get("current_mt5_prior_activity"):
        return True
    for acc in hr.get("historical_accounts") or []:
        if acc.get("prior_activity_profit"):
            return True
    return False


def repair_client(client_id, dry_run=False):
    data = get_client_data(client_id) or {}
    stats = data.get("statistics") or {}
    hr = stats.get("hedging_review") or {}
    if not _has_prior_activity(hr):
        return None

    before_actual = hr.get("actual_hedging_results")
    before_disc = hr.get("discrepancy")
    expected = compute_live_actual_hedging(data.get("account"), hr)
    if round(float(before_actual or 0), 2) == round(expected, 2):
        return None

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
