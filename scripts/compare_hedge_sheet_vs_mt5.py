#!/usr/bin/env python3
"""
Compare hedging totals: Google Sheet / evaluation-derived stats vs MT5 (stored & recomputed).

Reads live data from the dashboard DB for one client_id (default: Aaron).

The Stats UI \"Net Profit In Progress -> Hedging Results\" line is:
    cashflow_inprogress.hedging_results
    + cashflow_inprogress.farming_results
    + hedging_review.discrepancy
which equals MT5 actual hedging when discrepancy is maintained.

If the dashboard showed a small dollar gap vs MT5 while this script matched the DB,
that was usually renderStats overwriting cashflow with client-side aggregateCashflowFromEvals;
non-BEF views now keep API statistics so the card matches MT5.

Usage:
    python scripts/compare_hedge_sheet_vs_mt5.py
    python scripts/compare_hedge_sheet_vs_mt5.py --client Aaron
    python scripts/compare_hedge_sheet_vs_mt5.py --client Aaron --recalc
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)


def _f(x) -> float:
    try:
        return float(x if x is not None else 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v: float) -> str:
    return f"${v:,.2f}"


def live_actual_from_blob(data: dict) -> tuple[float, dict]:
    """
    Same formula as dashboard hedging merge / financial_overview trader stats:
    combined_bal - (combined_dep + combined_with) - prior_activity
    """
    acct = data.get("account") or {}
    hr = (data.get("statistics") or {}).get("hedging_review") or {}

    mt5_dep = _f(acct.get("total_deposits"))
    mt5_with = _f(acct.get("total_withdrawals"))
    mt5_bal = _f(acct.get("balance"))

    hist_dep = hist_with = hist_bal = 0.0
    prior_activity = _f(hr.get("current_mt5_prior_activity"))

    hist_rows = []
    for ha in hr.get("historical_accounts") or []:
        if not isinstance(ha, dict):
            continue
        d = _f(ha.get("deposits"))
        w = _f(ha.get("withdrawals"))
        b = _f(ha.get("final_balance"))
        p = _f(ha.get("prior_activity_profit"))
        hist_dep += d
        hist_with += w
        hist_bal += b
        prior_activity += p
        hist_rows.append({"deposits": d, "withdrawals": w, "final_balance": b, "prior_activity_profit": p})

    combined_dep = mt5_dep + hist_dep
    combined_with = mt5_with + hist_with
    combined_bal = mt5_bal + hist_bal

    live = combined_bal - (combined_dep + combined_with) - prior_activity

    detail = {
        "current_account": {"total_deposits": mt5_dep, "total_withdrawals": mt5_with, "balance": mt5_bal},
        "historical_sums": {"deposits": hist_dep, "withdrawals": hist_with, "final_balance": hist_bal},
        "combined_deposits": combined_dep,
        "combined_withdrawals": combined_with,
        "combined_balance": combined_bal,
        "prior_activity_total": prior_activity,
        "historical_account_count": len(hr.get("historical_accounts") or []),
    }
    return live, detail


def print_report(client_id: str, recalc: bool) -> None:
    from dashboard.database import get_client_data

    data = get_client_data(client_id)
    if not data:
        print(f"No client row found for client_id={client_id!r}")
        sys.exit(1)

    stats = data.get("statistics") or {}
    cf = stats.get("cashflow_inprogress") or {}
    hr = stats.get("hedging_review") or {}

    h_sheet = _f(cf.get("hedging_results"))
    f_sheet = _f(cf.get("farming_results"))
    sheet_combo = h_sheet + f_sheet

    hr_sheet_total = _f(hr.get("sheet_hedging_results"))
    actual_stored = _f(hr.get("actual_hedging_results"))
    disc_stored = _f(hr.get("discrepancy"))

    live_recomputed, detail = live_actual_from_blob(data)

    ui_hedging_line = sheet_combo + disc_stored

    print()
    print(f"=== Hedge sheet vs MT5 -- client_id={client_id!r} ===")
    print()
    print("--- Stored statistics.cashflow_inprogress (sheet rollups) ---")
    print(f"  hedging_results (HR cols):     {_fmt(h_sheet)}")
    print(f"  farming_results (Hedge Day):   {_fmt(f_sheet)}")
    print(f"  Sum (hedging + farming):       {_fmt(sheet_combo)}")
    print()
    print("--- Stored statistics.hedging_review ---")
    print(f"  sheet_hedging_results:         {_fmt(hr_sheet_total)}")
    print(f"  actual_hedging_results (MT5):{_fmt(actual_stored)}")
    print(f"  discrepancy (stored):        {_fmt(disc_stored)}")
    print(f"  Check actual - sheet_total:   {_fmt(actual_stored - hr_sheet_total)}")
    print()
    print("--- Recomputed MT5 actual from account + hedging_review (balance formula) ---")
    ca = detail["current_account"]
    print(f"  Current MT5 deposits:          {_fmt(ca['total_deposits'])}")
    print(f"  Current MT5 withdrawals:     {_fmt(ca['total_withdrawals'])}")
    print(f"  Current MT5 balance:         {_fmt(ca['balance'])}")
    hs = detail["historical_sums"]
    print(f"  Historical sum deposits:          {_fmt(hs['deposits'])}")
    print(f"  Historical sum withdrawals:    {_fmt(hs['withdrawals'])}")
    print(f"  Historical sum final_balance:   {_fmt(hs['final_balance'])}")
    print(f"  Prior activity (total):      {_fmt(detail['prior_activity_total'])}")
    print(f"  Historical accounts count:    {detail['historical_account_count']}")
    print(f"  -> Live actual (recomputed):    {_fmt(live_recomputed)}")
    print(f"  Delta stored_actual - recomputed: {_fmt(actual_stored - live_recomputed)}")
    print()
    print('--- Matches Stats UI "Net Profit In Progress -> Hedging Results" ---')
    print(f"  cf_hedging + cf_farming + discrepancy = {_fmt(ui_hedging_line)}")
    print(f"  (Should equal MT5 actual when disc is maintained; recomputed actual {_fmt(live_recomputed)})")
    print(f"  Delta UI_line - recomputed_actual: {_fmt(ui_hedging_line - live_recomputed)}")
    print()

    if abs(hr_sheet_total - sheet_combo) > 0.02:
        print(
            "[!] sheet_hedging_results differs from cf_hedging+cf_farming by "
            f"{_fmt(hr_sheet_total - sheet_combo)} -- stats tab override or stale merge?"
        )
        print()

    if recalc:
        print("--- Fresh calculate_statistics(evaluations, mt5_account=…) ---")
        from utils.data_processor import calculate_statistics

        evals = list(data.get("evaluations") or [])
        hist = hr.get("historical_accounts")
        fresh = calculate_statistics(
            evals,
            mt5_account=data.get("account"),
            historical_accounts=hist,
        )
        fr_hr = fresh.get("hedging_review") or {}
        fr_cf = fresh.get("cashflow_inprogress") or {}
        print(f"  Fresh sheet_hedging_results:   {_fmt(_f(fr_hr.get('sheet_hedging_results')))}")
        print(f"  Fresh cf hedging+farming:      {_fmt(_f(fr_cf.get('hedging_results')) + _f(fr_cf.get('farming_results')))}")
        print(f"  Fresh actual (processor):       {_fmt(_f(fr_hr.get('actual_hedging_results')))}")
        print(f"  Fresh discrepancy:             {_fmt(_f(fr_hr.get('discrepancy')))}")
        print()

    print("Raw hedging_review JSON (for deep debugging):")
    print(json.dumps(hr, indent=2, default=str)[:8000])
    if len(json.dumps(hr, default=str)) > 8000:
        print("  ... truncated ...")


def main():
    ap = argparse.ArgumentParser(description="Compare sheet hedging vs MT5 for one client.")
    ap.add_argument("--client", default="Aaron", help="clients_data.client_id (default: Aaron)")
    ap.add_argument(
        "--recalc",
        action="store_true",
        help="Run calculate_statistics from evaluations + MT5 (slower, verifies processor)",
    )
    args = ap.parse_args()
    print_report(args.client, args.recalc)


if __name__ == "__main__":
    main()
