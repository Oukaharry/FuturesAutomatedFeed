"""
scripts/_debug_hedging_results_mismatch.py
----------------------------------------
Print the exact values used by the 'Hedging Results mismatch' quality check.

Usage:
  python scripts/_debug_hedging_results_mismatch.py "Reece"
  python scripts/_debug_hedging_results_mismatch.py "Rob Madsen"
"""

import json
import os
import sys

# Ensure repo root is importable (so `import dashboard...` works when running from /scripts)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _to_float(v):
    try:
        if v is None:
            return 0.0
        s = str(v).replace("$", "").replace(",", "").strip()
        if s == "":
            return 0.0
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/_debug_hedging_results_mismatch.py \"Client Name\"")
        raise SystemExit(2)

    client_id = sys.argv[1]

    try:
        from dashboard.database import get_client_data
    except Exception as e:
        print(f"Failed to import dashboard.database.get_client_data: {e}")
        raise

    data = get_client_data(client_id) or {}
    stats = data.get("statistics", {}) if isinstance(data, dict) else {}
    hr = stats.get("hedging_review", {}) if isinstance(stats, dict) else {}
    cf = stats.get("cashflow_inprogress", {}) if isinstance(stats, dict) else {}
    acct = data.get("account", {}) if isinstance(data, dict) else {}

    mt5_dep = _to_float(acct.get("total_deposits", hr.get("total_deposits")))
    mt5_wd = _to_float(acct.get("total_withdrawals", hr.get("total_withdrawals")))
    mt5_bal = _to_float(acct.get("balance", hr.get("current_balance")))

    hist = hr.get("historical_accounts") or []
    hist_dep = hist_wd = hist_bal = 0.0

    current_prior = _to_float(hr.get("current_mt5_prior_activity"))
    total_prior = current_prior
    if isinstance(hist, list):
        for a in hist:
            if not isinstance(a, dict):
                continue
            hist_dep += _to_float(a.get("deposits"))
            hist_wd += _to_float(a.get("withdrawals"))
            hist_bal += _to_float(a.get("final_balance"))
            total_prior += _to_float(a.get("prior_activity_profit"))

    combined_dep = mt5_dep + hist_dep
    combined_wd = mt5_wd + hist_wd
    combined_bal = mt5_bal + hist_bal

    mt5_profit_current = round(mt5_bal - (mt5_dep + mt5_wd) - current_prior, 2)
    mt5_profit_combined = round(combined_bal - (combined_dep + combined_wd) - total_prior, 2)

    hedge_total_display = round(
        _to_float(cf.get("hedging_results")) + _to_float(cf.get("farming_results")) + _to_float(hr.get("discrepancy")),
        2,
    )

    print("=" * 70)
    print(f"Client: {client_id}")
    print("=" * 70)
    print("\n--- MT5 current (yellow row inputs) ---")
    print(f"balance:           {mt5_bal:.2f}")
    print(f"deposits:          {mt5_dep:.2f}")
    print(f"withdrawals:       {mt5_wd:.2f}")
    print(f"prior_activity:    {current_prior:.2f}")
    print(f"profit_current:    {mt5_profit_current:.2f}")

    print("\n--- MT5 historical (green totals inputs) ---")
    print(f"hist_count:        {len(hist) if isinstance(hist, list) else 0}")
    print(f"hist_deposits:     {hist_dep:.2f}")
    print(f"hist_withdrawals:  {hist_wd:.2f}")
    print(f"hist_final_balance:{hist_bal:.2f}")
    print(f"prior_total:       {total_prior:.2f}")
    print(f"profit_combined:   {mt5_profit_combined:.2f}")

    print("\n--- Sheet (Stats) ---")
    print(f"cashflow_inprogress.hedging_results: {_to_float(cf.get('hedging_results')):.2f}")
    print(f"cashflow_inprogress.farming_results: {_to_float(cf.get('farming_results')):.2f}")
    print(f"hedging_review.discrepancy:           {_to_float(hr.get('discrepancy')):.2f}")
    print(f"hedge_total_display:                 {hedge_total_display:.2f}")

    print("\n--- Diffs ---")
    print(f"(current - hedge_total):  {round(mt5_profit_current - hedge_total_display, 2):.2f}")
    print(f"(combined - hedge_total): {round(mt5_profit_combined - hedge_total_display, 2):.2f}")

    print("\nRaw keys (for DB verification):")
    print("account:", json.dumps(acct, indent=2, default=str)[:2000])
    print("hedging_review keys:", json.dumps({k: hr.get(k) for k in ('discrepancy','current_mt5_prior_activity','historical_accounts')}, indent=2, default=str)[:2000])
    print("cashflow_inprogress keys:", json.dumps({k: cf.get(k) for k in ('hedging_results','farming_results')}, indent=2, default=str)[:2000])


if __name__ == "__main__":
    main()

