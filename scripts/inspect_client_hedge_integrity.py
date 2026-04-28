"""
Verify evaluation rows: stored Hedge Net / Hedge Net.1 match the same formulas as
dashboard/app.py recalculate_hedge_nets() and the sheet (data_processor.py).

Phase 1 — Hedge Net (when Status P1 is 'Fail' and Hedge Result 1 is set):
  Hedge Net = -Fee + Hedge Result 1 + … + Hedge Result 5

Funded — Hedge Net.1:
  If Status is 'Completed':
    sum(Payout 1..6) + sum(funded HR 1.1–7) + sum(phase-1 HR 1–5) - Fee - Activation Fee
    + sum(Hedge Day 1..50)
  If Status is 'Fail':
    sum(funded HR) + sum(phase-1 HR) - Fee - Activation Fee
  Otherwise: blank

Run from repo root (same Python / DATABASE_URL as the app):

  python scripts/inspect_client_hedge_integrity.py "Thak Mano"
  python scripts/inspect_client_hedge_integrity.py "Thak Mano" --large-hr1 400
  python scripts/inspect_client_hedge_integrity.py "Thak Mano" --account 99880

On PythonAnywhere:
  export PYTHONPATH=~/MT5Dashboard/dashboard:~/MT5Dashboard
  cd ~/MT5Dashboard
  python scripts/inspect_client_hedge_integrity.py "Thak Mano"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")
for p in (DASH, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
os.chdir(DASH)

from database import get_client_data  # noqa: E402


def _num(val: object) -> float:
    if val is None or str(val).strip() in ("", "-"):
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _is_blank(val: object) -> bool:
    return val is None or str(val).strip() in ("", "-")


def recalculate_hedge_nets(evs: list) -> list:
    """Same logic as dashboard.app.recalculate_hedge_nets (kept here to avoid importing app)."""
    for ev in evs or []:
        if not isinstance(ev, dict):
            continue
        status_p1 = str(ev.get("Status P1", "")).strip()
        if _is_blank(ev.get("Hedge Result 1")) or status_p1 != "Fail":
            ev["Hedge Net"] = ""
        else:
            fee = _num(ev.get("Fee"))
            hr_sum = sum(_num(ev.get(f"Hedge Result {i}")) for i in range(1, 6))
            ev["Hedge Net"] = -fee + hr_sum

        status = str(ev.get("Status") or ev.get("Status Funded", "")).strip()
        sum_phase1 = sum(_num(ev.get(f"Hedge Result {i}")) for i in range(1, 6))
        sum_funded = sum(
            _num(ev.get(c))
            for c in [
                "Hedge Result 1.1",
                "Hedge Result 2.1",
                "Hedge Result 3.1",
                "Hedge Result 4.1",
                "Hedge Result 5.1",
                "Hedge Result 6",
                "Hedge Result 7",
            ]
        )
        fee = _num(ev.get("Fee"))
        activation_fee = _num(ev.get("Activation Fee"))

        if status == "Completed":
            sum_payouts = sum(_num(ev.get(f"Payout {i}")) for i in range(1, 7))
            sum_days = sum(_num(ev.get(f"Hedge Day {i}")) for i in range(1, 51))
            ev["Hedge Net.1"] = sum_payouts + sum_funded + sum_phase1 - fee - activation_fee + sum_days
        elif status == "Fail":
            ev["Hedge Net.1"] = sum_funded + sum_phase1 - fee - activation_fee
        else:
            ev["Hedge Net.1"] = ""
    return evs


def _close(a: object, b: object, tol: float = 0.02) -> bool:
    if (a in (None, "")) and (b in (None, "")):
        return True
    if a in (None, "") or b in (None, ""):
        return False
    return abs(_num(a) - _num(b)) < tol


def _acct(ev: dict) -> str:
    return str(ev.get("Account") or ev.get("Account #") or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Check Hedge Net / Hedge Net.1 vs app formulas.")
    ap.add_argument("client", help="Client id (e.g. Thak Mano)")
    ap.add_argument(
        "--account",
        default="",
        help="Only print detail for rows whose account string contains this (e.g. 99880)",
    )
    ap.add_argument(
        "--large-hr1",
        type=float,
        metavar="ABS",
        default=None,
        help="Flag Fail rows where abs(Hedge Result 1) exceeds this (e.g. 400 to spot outliers vs ~110)",
    )
    ap.add_argument("--tol", type=float, default=0.02, help="Equality tolerance (default 0.02)")
    args = ap.parse_args()

    d = get_client_data(args.client.strip())
    if not d:
        print(f"No clients_data for client {args.client!r}")
        return 1

    evs = [e for e in (d.get("evaluations") or []) if isinstance(e, dict)]
    if not evs:
        print("No evaluation rows.")
        return 0

    disc = 0
    for i, ev in enumerate(evs):
        raw = json.loads(json.dumps(ev))
        calc = recalculate_hedge_nets([raw])[0]
        if not _close(ev.get("Hedge Net"), calc.get("Hedge Net"), args.tol) or not _close(
            ev.get("Hedge Net.1"), calc.get("Hedge Net.1"), args.tol
        ):
            disc += 1
            firm = ev.get("Prop Firm", "?")
            print(
                f"[mismatch] row_index={i} #sheet≈{i+1}  {firm}  {_acct(ev) or 'no account'}\n"
                f"  Hedge Net:    stored {ev.get('Hedge Net')!r}  recalc {calc.get('Hedge Net')!r}\n"
                f"  Hedge Net.1:  stored {ev.get('Hedge Net.1')!r}  recalc {calc.get('Hedge Net.1')!r}"
            )

    if disc == 0:
        print(f"OK — all {len(evs)} rows: stored Hedge Net / Hedge Net.1 match formula (tol={args.tol}).")
    else:
        print(f"\nTotal mismatches: {disc}")

    if args.account.strip():
        sub = args.account.strip()
        for i, ev in enumerate(evs):
            if sub not in _acct(ev).replace(" ", ""):
                continue
            print(f"\n--- Detail row index {i} (account match {sub!r}) ---")
            sp1 = str(ev.get("Status P1", "")).strip()
            st = str(ev.get("Status") or ev.get("Status Funded", "")).strip()
            print(f"  Prop Firm: {ev.get('Prop Firm')!r}  Account: {_acct(ev)!r}")
            print(f"  Status P1: {sp1!r}  Status: {st!r}")
            print(f"  Fee: {ev.get('Fee')!r}  Activation Fee: {ev.get('Activation Fee')!r}")
            for j in range(1, 6):
                v = ev.get(f"Hedge Result {j}")
                if v not in (None, "", "-"):
                    print(f"  Hedge Result {j}: {v!r}")
            hsum = sum(_num(ev.get(f"Hedge Result {j}")) for j in range(1, 6))
            fee = _num(ev.get("Fee"))
            print(f"  sum(HR1..5) = {hsum:.2f}  |  -Fee + sum = {-fee + hsum:.2f}  |  stored Hedge Net = {ev.get('Hedge Net')!r}")
            r = recalculate_hedge_nets([json.loads(json.dumps(ev))])[0]
            print(f"  recalc Hedge Net: {r.get('Hedge Net')!r}  Hedge Net.1: {r.get('Hedge Net.1')!r}")

    if args.large_hr1 is not None:
        lim = float(args.large_hr1)
        print(f"\n--- Fail rows with abs(Hedge Result 1) > {lim} (review data entry) ---")
        nflag = 0
        for i, ev in enumerate(evs):
            if str(ev.get("Status P1", "")).strip() != "Fail":
                continue
            if _is_blank(ev.get("Hedge Result 1")):
                continue
            h1 = _num(ev.get("Hedge Result 1"))
            if abs(h1) <= lim:
                continue
            nflag += 1
            print(
                f"  row {i}  {ev.get('Prop Firm', '?')!r}  {_acct(ev)}  "
                f"HR1={h1:,.2f}  Fee={_num(ev.get('Fee')):,.2f}  Hedge Net={_num(ev.get('Hedge Net')):,.2f}"
            )
        if nflag == 0:
            print("  (none)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
