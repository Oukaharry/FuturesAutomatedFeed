#!/usr/bin/env python3
"""
Reset MT5/statistics context for a client so Stats doesn't show phantom hedging.

Why this exists:
The Stats tab computes "Hedging Results" as:
  cashflow_inprogress.hedging_results + cashflow_inprogress.farming_results + hedging_review.discrepancy
and it computes "actual hedging" from MT5 `account` totals (deposits/withdrawals/balance) unless the
server provides `hedging_review.actual_hedging_results`.

So even if evaluation hedge cells are blank, a prior MT5 push (or wrong account linkage) can leave:
  - data.account.total_deposits / total_withdrawals / balance
  - statistics.hedging_review.{total_deposits,total_withdrawals,current_balance,discrepancy,historical_accounts,...}
which makes the dashboard show large hedging results.

This script clears ONLY:
  - clients_data.account: MT5 totals (deposits/withdrawals/balance/profit/equity/margins)
  - clients_data.statistics.hedging_review: MT5 snapshot + discrepancy + historical accounts
  - clients_data.statistics: recomputes per-firm aggregates from current evaluations (prevents stale fees/rows)
    while forcing hedging_review discrepancy=0 so net profit isn't inflated by old MT5 pushes.

Dry-run by default. Use --apply to persist changes.

Usage:
  python scripts/reset_client_mt5_stats_context.py --client "Fallback"
  python scripts/reset_client_mt5_stats_context.py --client "Fallback" --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _backup_path(client_id: str, out_dir: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (client_id or "client"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, f"_backup_{safe}_mt5_stats_{ts}.json")


def _to_float(v: Any) -> float:
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _summarize(d: dict) -> dict:
    st = d.get("statistics") or {}
    cf = st.get("cashflow_inprogress") or {}
    hr = st.get("hedging_review") or {}
    acct = d.get("account") or {}
    return {
        "account": {k: acct.get(k) for k in ("total_deposits", "total_withdrawals", "balance", "equity", "profit")},
        "cashflow_inprogress": {k: cf.get(k) for k in ("payouts", "challenge_fees", "hedging_results", "farming_results", "net_profit")},
        "hedging_review": {k: hr.get(k) for k in ("total_deposits", "total_withdrawals", "current_balance", "actual_hedging_results", "sheet_hedging_results", "discrepancy", "current_mt5_prior_activity", "historical_accounts")},
    }


def _reset_account(acct: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(acct, dict):
        acct = {}
    out = dict(acct)
    # Keep identity-ish fields (login/server/name/company/currency) but zero totals.
    for k in (
        "total_deposits",
        "total_withdrawals",
        "balance",
        "equity",
        "profit",
        "margin",
        "margin_free",
        "margin_level",
        "credit",
    ):
        if k in out:
            out[k] = 0.0
    return out


def _reset_hedging_review(hr: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(hr, dict):
        hr = {}
    out = dict(hr)
    # Reset everything that can force a non-zero discrepancy / "actual hedging".
    out["actual_hedging_results"] = 0.0
    out["total_deposits"] = 0.0
    out["total_withdrawals"] = 0.0
    out["current_balance"] = 0.0
    out["historical_accounts"] = []
    out["historical_deposits"] = 0.0
    out["historical_withdrawals"] = 0.0
    out["historical_balance"] = 0.0
    out["current_mt5_prior_activity"] = 0.0
    out["discrepancy"] = 0.0
    return out


def _reset_cashflow_section(sec: Dict[str, Any], *, challenge_fees: float | None = None) -> Dict[str, Any]:
    if not isinstance(sec, dict):
        sec = {}
    out = dict(sec)
    # Leave challenge_fees as-is by default (fees are real sheet data).
    if challenge_fees is not None:
        out["challenge_fees"] = float(challenge_fees)
    out.setdefault("payouts", 0.0)
    out.setdefault("hedging_results", 0.0)
    out.setdefault("farming_results", 0.0)
    # With discrepancy forced to 0 in hedging_review, net_profit should be:
    # payouts + hedging + farming - challenge_fees
    out["net_profit"] = round(
        _to_float(out.get("payouts"))
        + _to_float(out.get("hedging_results"))
        + _to_float(out.get("farming_results"))
        - _to_float(out.get("challenge_fees")),
        2,
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset MT5/statistics context for one client.")
    ap.add_argument("--client", default="Fallback", help="Exact client_id as stored in DB (default: Fallback)")
    ap.add_argument("--apply", action="store_true", help="Persist changes to DB (default: dry-run)")
    ap.add_argument("--backup-dir", default=".", help="Directory for backup JSON when using --apply")
    ap.add_argument(
        "--zero-fees",
        action="store_true",
        help="Also set cashflow challenge_fees to 0.00 (default: keep fees from sheet).",
    )
    args = ap.parse_args()

    from dashboard.database import get_client_data, save_client_data

    client_id = str(args.client or "").strip()
    if not client_id:
        print("Missing --client")
        return 2

    data = get_client_data(client_id) or {}
    if not isinstance(data, dict) or not data:
        print(f"Client {client_id!r}: no data found; aborting.")
        return 2

    before = _summarize(data)

    st = data.get("statistics") if isinstance(data.get("statistics"), dict) else {}
    hr_existing = (st.get("hedging_review") if isinstance(st.get("hedging_review"), dict) else {}) if isinstance(st, dict) else {}
    acct = data.get("account") if isinstance(data.get("account"), dict) else {}

    new_account = _reset_account(acct)

    def _parse_money(v: Any) -> float:
        try:
            s = str(v or "").replace("$", "").replace(",", "").strip()
            if s in ("", "-", "--", "—", "–"):
                return 0.0
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    def _is_terminal_status(raw: Any) -> bool:
        s = str(raw or "").strip().lower()
        if not s:
            return False
        # Match quality-scan semantics broadly.
        return any(t in s for t in ("fail", "failed", "breach", "closed", "sl", "complete", "completed", "deleted"))

    def _recompute_prop_firm_rollups(evaluations_list: list) -> tuple[dict, dict, dict, dict]:
        """
        Rebuild a minimal subset of statistics needed for the Stats UI "By Prop Firm" table:
          - evaluation_data: fees + counts for eval phase (Status P1)
          - funded_data: activation fees + counts for funded phase (Status / Status Funded)
          - eval_totals / funded_totals: summed counts (best-effort)

        This avoids importing utils.data_processor (which pulls pandas).
        """
        eval_data: Dict[str, Dict[str, Any]] = {}
        funded_data: Dict[str, Dict[str, Any]] = {}
        eval_totals = {"total_running": 0, "not_started": 0, "ongoing": 0, "total_passed": 0, "total_failed": 0, "avg_net_failed": 0.0, "funded_rate": 0.0}
        funded_totals = {"not_started": 0, "ongoing": 0, "failed": 0, "completed": 0, "avg_net_failed": 0.0, "avg_net_completed": 0.0, "total_funding": 0.0}

        for ev in evaluations_list or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("_deleted"):
                continue

            firm = str(ev.get("Prop Firm") or "").strip() or "Unknown"
            fee = _parse_money(ev.get("Fee"))
            act_fee = _parse_money(ev.get("Activation Fee"))

            status_p1 = str(ev.get("Status P1") or "").strip().lower()
            status_f = str(ev.get("Status") or ev.get("Status Funded") or "").strip().lower()

            ed = eval_data.setdefault(
                firm,
                {"total_running": 0, "not_started": 0, "ongoing": 0, "total_passed": 0, "total_failed": 0, "fees": 0.0},
            )
            fd = funded_data.setdefault(
                firm,
                {"not_started": 0, "ongoing": 0, "failed": 0, "completed": 0, "fees": 0.0, "total_funding": 0.0},
            )

            # Fees: match sheet-ish meaning (challenge fee + activation fee are both "costs").
            ed["fees"] = round(float(ed.get("fees") or 0.0) + fee, 2)
            fd["fees"] = round(float(fd.get("fees") or 0.0) + act_fee, 2)

            # Eval phase counts (Status P1)
            if not status_p1 or "not started" in status_p1:
                ed["not_started"] += 1
                eval_totals["not_started"] += 1
            elif "pass" in status_p1:
                ed["total_passed"] += 1
                eval_totals["total_passed"] += 1
            elif "fail" in status_p1:
                ed["total_failed"] += 1
                eval_totals["total_failed"] += 1
            else:
                ed["ongoing"] += 1
                eval_totals["ongoing"] += 1
            ed["total_running"] += 1
            eval_totals["total_running"] += 1

            # Funded phase counts (Status / Status Funded)
            if not status_f or "not started" in status_f or status_f in ("-", "--"):
                fd["not_started"] += 1
                funded_totals["not_started"] += 1
            elif "complete" in status_f:
                fd["completed"] += 1
                funded_totals["completed"] += 1
            elif "fail" in status_f or "breach" in status_f:
                fd["failed"] += 1
                funded_totals["failed"] += 1
            else:
                fd["ongoing"] += 1
                funded_totals["ongoing"] += 1

        # Best-effort funded rate
        tr = eval_totals["total_running"] or 0
        eval_totals["funded_rate"] = round((eval_totals["total_passed"] / tr * 100.0), 2) if tr else 0.0
        return eval_data, funded_data, eval_totals, funded_totals

    # Recompute just the per-firm rollups from current evaluations to avoid stale fee rows.
    evaluations = data.get("evaluations") or []
    if not isinstance(evaluations, list):
        evaluations = []
    eval_data, funded_data, eval_totals, funded_totals = _recompute_prop_firm_rollups(evaluations)

    recomputed: Dict[str, Any] = dict(st) if isinstance(st, dict) else {}
    recomputed["evaluation_data"] = eval_data
    recomputed["funded_data"] = funded_data
    recomputed["eval_totals"] = eval_totals
    recomputed["funded_totals"] = funded_totals

    # Force MT5 context to zero regardless of recompute output.
    new_hr = _reset_hedging_review(hr_existing)
    recomputed["hedging_review"] = new_hr

    # Optionally zero fees in the cashflow cards (normally we keep fees from sheet/evals).
    fees = 0.0 if args.zero_fees else None
    recomputed["cashflow_inprogress"] = _reset_cashflow_section(
        recomputed.get("cashflow_inprogress") if isinstance(recomputed.get("cashflow_inprogress"), dict) else {},
        challenge_fees=fees,
    )
    recomputed["profitability_completed"] = _reset_cashflow_section(
        recomputed.get("profitability_completed") if isinstance(recomputed.get("profitability_completed"), dict) else {},
        challenge_fees=fees,
    )
    new_cf = recomputed["cashflow_inprogress"]
    new_stats = recomputed

    after_preview = {
        "account": {k: new_account.get(k) for k in ("total_deposits", "total_withdrawals", "balance", "equity", "profit")},
        "cashflow_inprogress": {k: new_cf.get(k) for k in ("payouts", "challenge_fees", "hedging_results", "farming_results", "net_profit")},
        "hedging_review": {k: new_hr.get(k) for k in ("total_deposits", "total_withdrawals", "current_balance", "actual_hedging_results", "discrepancy", "historical_accounts")},
    }

    print(f"Client: {client_id}")
    print("Before:")
    print(json.dumps(before, indent=2))
    print("After (preview):")
    print(json.dumps(after_preview, indent=2))

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to save.")
        return 0

    os.makedirs(args.backup_dir, exist_ok=True)
    bp = _backup_path(client_id, args.backup_dir)
    with open(bp, "w", encoding="utf-8") as f:
        json.dump({"before": before, "raw": data}, f, indent=2, ensure_ascii=False)
    print(f"Backup written: {bp}")

    ok = save_client_data(
        client_id,
        {
            "account": new_account,
            "statistics": new_stats,
        },
        overwrite=False,
    )
    if not ok:
        print("Save failed.")
        return 1

    print("Saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

