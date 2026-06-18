"""
Repair inflated hedging_review / net profit from MT5 discrepancy bugs.

1. Historical closed accounts wrongly included in discrepancy (Reece-style).
2. MT5 balance treated as hedging P&L when deposits/withdrawals/prior are zero.

Usage:
  python scripts/repair_hedging_prior_activity.py
  python scripts/repair_hedging_prior_activity.py "David S"
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
from dashboard.watermark_service import get_all_daily_watermarks, save_daily_profit
from utils.data_processor import (
    _sheet_base_net_profit,
    apply_discrepancy_to_net_profit,
    hedging_discrepancy_inflated_from_unfunded_balance,
    hedging_discrepancy_is_stale,
    sync_hedging_review_discrepancy,
)

_SPIKE_THRESHOLD = 50000.0


def _find_pre_inflation_baseline(client_id):
    """Return (baseline_net, baseline_date) from the day before a large watermark jump."""
    watermarks = get_all_daily_watermarks(client_id)
    if len(watermarks) < 2:
        return None, None
    for i in range(len(watermarks) - 1, 0, -1):
        _, profit = watermarks[i]
        baseline_date, baseline_net = watermarks[i - 1]
        if float(profit) - float(baseline_net) >= _SPIKE_THRESHOLD:
            return float(baseline_net), baseline_date
    return None, None


def repair_unfunded_balance_inflation(client_id, dry_run=False):
    data = get_client_data(client_id) or {}
    stats = data.get("statistics") or {}
    hr = stats.get("hedging_review") or {}
    if not hedging_discrepancy_inflated_from_unfunded_balance(stats, data.get("account")):
        return None

    baseline_net, baseline_date = _find_pre_inflation_baseline(client_id)
    if baseline_net is None:
        return None

    before_actual = hr.get("actual_hedging_results")
    before_disc = hr.get("discrepancy")
    before_net = (stats.get("cashflow_inprogress") or {}).get("net_profit")

    sheet_hr = float(hr.get("sheet_hedging_results") or 0)
    base = _sheet_base_net_profit(stats)
    target_disc = round(baseline_net - base, 2)
    target_actual = round(sheet_hr + target_disc, 2)
    hr["actual_hedging_results"] = target_actual
    hr["discrepancy"] = target_disc
    apply_discrepancy_to_net_profit(stats)
    data["statistics"] = stats

    if not dry_run:
        save_client_data(client_id, data)
        after_net = (stats.get("cashflow_inprogress") or {}).get("net_profit")
        watermarks = get_all_daily_watermarks(client_id)
        for wm_date, _ in watermarks:
            if wm_date > baseline_date:
                save_daily_profit(client_id, after_net, wm_date.strftime("%Y-%m-%d"), source="repair")

    return {
        "client_id": client_id,
        "repair_type": "unfunded_balance_inflation",
        "baseline_date": str(baseline_date),
        "baseline_net": baseline_net,
        "before_actual": before_actual,
        "after_actual": hr.get("actual_hedging_results"),
        "before_discrepancy": before_disc,
        "after_discrepancy": hr.get("discrepancy"),
        "before_net": before_net,
        "after_net": (stats.get("cashflow_inprogress") or {}).get("net_profit"),
    }


def repair_stale_historical_inflation(client_id, dry_run=False):
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
        "repair_type": "stale_historical_inflation",
        "before_actual": before_actual,
        "after_actual": hr.get("actual_hedging_results"),
        "before_discrepancy": before_disc,
        "after_discrepancy": hr.get("discrepancy"),
        "before_net": before_net,
        "after_net": (stats.get("cashflow_inprogress") or {}).get("net_profit"),
    }


def repair_client(client_id, dry_run=False):
    result = repair_unfunded_balance_inflation(client_id, dry_run=dry_run)
    if result:
        return result
    return repair_stale_historical_inflation(client_id, dry_run=dry_run)


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
