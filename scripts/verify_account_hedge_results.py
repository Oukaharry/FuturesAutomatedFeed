"""
Verify hedge results for a specific evaluation row / account.

This script reads `clients_data.evaluations` from Postgres and computes the
same "hedging results" sums used by the dashboard Stats logic:

  Phase-1 hedges = SUM(Hedge Result 1..5)
  Funded hedges  = SUM(Hedge Result 1.1..5.1, Hedge Result 6, Hedge Result 7)
  Total hedging  = Phase-1 + Funded

Row numbering:
  The dashboard commonly treats evaluations row numbers as (index + 3),
  i.e. evaluation index 0 corresponds to sheet/dashboard row 3.

Examples:
  python scripts/verify_account_hedge_results.py --client "Thak Mano" --row 586
  python scripts/verify_account_hedge_results.py --client "Thak Mano" --account "TDFYSL50149986736"
  python scripts/verify_account_hedge_results.py --client "Ian" --account "TDFYSL50140986736" --phase evaluation

Optional:
  --expected <number>  Compare against a dashboard value you read manually.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dashboard.database import get_connection  # type: ignore
except ModuleNotFoundError as e:  # pragma: no cover
    raise SystemExit(
        "Missing Postgres dependency.\n"
        f"Error: {e}\n\n"
        "Install it, then rerun:\n"
        "  pip install psycopg2-binary\n"
        "  # or: pip install psycopg2\n"
    ) from e
except Exception as e:  # pragma: no cover
    raise SystemExit(f"Failed to import Postgres database module: {e}") from e


P1_HEDGE_COLS = [f"Hedge Result {i}" for i in range(1, 6)]
FUNDED_HEDGE_COLS = [
    "Hedge Result 1.1",
    "Hedge Result 2.1",
    "Hedge Result 3.1",
    "Hedge Result 4.1",
    "Hedge Result 5.1",
    "Hedge Result 6",
    "Hedge Result 7",
]


def _norm(s: Any) -> str:
    return str(s or "").strip().casefold()


def parse_currency(val: Any) -> float:
    """
    Lightweight currency parser (kept local; avoids pandas dependency).
    Unparseable strings count as 0.0 (matching typical Sheets SUM behavior).
    """
    if val is None:
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val)
        s = (
            s.replace("$", "")
            .replace("\u20ac", "")
            .replace("\u00a3", "")
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .strip()
        )
        if not s or s.lower() == "nan":
            return 0.0
        if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
            s = "-" + s[1:-1].strip()
        if "," in s:
            if "." not in s:
                if re.search(r",\d{1,2}$", s):
                    return 0.0
                s = s.replace(",", "")
            else:
                if re.search(r",\.", s):
                    return 0.0
                s = s.replace(",", "")
        return round(float(s), 2)
    except Exception:
        return 0.0


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _load_client_evaluations(client_name: str) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Returns (client_id, display_name, evaluations_list).
    Matches case-insensitively against:
      - clients_data.client_id
      - clients_data.identity JSON field "name"
    """
    wanted = _norm(client_name)
    # Fast path: try direct client_id match first (case-insensitive).
    with get_connection() as conn:  # type: ignore[misc]
        cur = conn.cursor()
        cur.execute(
            "SELECT client_id, identity, evaluations FROM clients_data WHERE LOWER(client_id) = ? LIMIT 5",
            (wanted,),
        )
        rows = cur.fetchall() or []

        # Fallback: search inside identity JSON text for an exact "name" match.
        # Identity is stored as TEXT in this project, so we pattern-match the serialized JSON.
        if not rows:
            # Identity is JSON stored as TEXT. This is a best-effort text match that
            # finds rows where identity contains `"name"` and the target name.
            cur.execute(
                "SELECT client_id, identity, evaluations FROM clients_data "
                "WHERE identity ILIKE ? LIMIT 5",
                (f'%\"name\"%\"{client_name}%\"%',),
            )
            rows = cur.fetchall() or []

    for row in rows:
        cid = str(row.get("client_id") or "").strip()
        identity_raw = row.get("identity") or "{}"
        evals_raw = row.get("evaluations") or "[]"

        try:
            identity = json.loads(identity_raw) if isinstance(identity_raw, str) else (identity_raw or {})
        except Exception:
            identity = {}
        try:
            evaluations = json.loads(evals_raw) if isinstance(evals_raw, str) else (evals_raw or [])
        except Exception:
            evaluations = []

        identity_name = ""
        if isinstance(identity, dict):
            identity_name = str(identity.get("name") or "").strip()

        if _norm(cid) == wanted or _norm(identity_name) == wanted:
            return cid, (identity_name or cid), evaluations

    raise SystemExit(f"No client match found for: {client_name!r}")


def _pick_evaluation(
    evaluations: List[Dict[str, Any]],
    row: Optional[int],
    account: Optional[str],
) -> Tuple[int, Dict[str, Any]]:
    if row is not None:
        idx = row - 3
        if idx < 0 or idx >= len(evaluations):
            raise SystemExit(f"Row {row} is out of range. Evaluations count: {len(evaluations)} (rows start at 3).")
        ev = evaluations[idx]
        if not isinstance(ev, dict):
            raise SystemExit(f"Row {row} exists but is not a dict evaluation.")
        return idx, ev

    if account:
        needle = _norm(account)
        hits = []
        for idx, ev in enumerate(evaluations):
            if not isinstance(ev, dict):
                continue
            # Match against both evaluation account fields (phase-1 and funded),
            # plus any legacy "Account" key if present.
            candidates = [
                str(ev.get("Account #") or "").strip(),
                str(ev.get("Account #.1") or "").strip(),
                str(ev.get("Account") or "").strip(),
            ]
            for acc in candidates:
                if needle and _norm(acc) == needle:
                    hits.append((idx, ev, acc))
                    break
        if not hits:
            # Fallback: substring match (some accounts may have prefixes/suffixes)
            hits2 = []
            for idx, ev in enumerate(evaluations):
                if not isinstance(ev, dict):
                    continue
                candidates = [
                    str(ev.get("Account #") or "").strip(),
                    str(ev.get("Account #.1") or "").strip(),
                    str(ev.get("Account") or "").strip(),
                ]
                for acc in candidates:
                    if needle and needle in _norm(acc):
                        hits2.append((idx, ev, acc))
                        break
            if not hits2:
                raise SystemExit(f"No evaluation found matching account: {account!r}")
            hits = hits2
        if len(hits) > 1:
            print(f"WARNING: multiple evaluations matched account {account!r}; using the first. Matches:")
            for idx, _ev, acc in hits[:10]:
                print(f"  - row {idx + 3}: {acc}")
        idx, ev, _acc = hits[0]
        return idx, ev

    raise SystemExit("Provide either --row or --account.")


def _sum_cols(ev: Dict[str, Any], cols: List[str]) -> Tuple[float, List[Tuple[str, float, Any]]]:
    parts: List[Tuple[str, float, Any]] = []
    total = 0.0
    for c in cols:
        raw = ev.get(c)
        val = parse_currency(raw)
        parts.append((c, val, raw))
        total += val
    return round(total, 2), parts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help='Client name to match (e.g. "Thak Mano")')
    ap.add_argument("--row", type=int, default=None, help="Dashboard/sheet row number (row = index + 3).")
    ap.add_argument("--account", default=None, help="Account number (substring match).")
    ap.add_argument(
        "--phase",
        choices=["evaluation", "funded", "both"],
        default="both",
        help="Which hedge columns to sum. 'evaluation' sums Hedge Result 1..5 only. Default: both.",
    )
    ap.add_argument(
        "--expected",
        type=float,
        default=None,
        help="Optional: the hedge total you see on the dashboard (number).",
    )
    args = ap.parse_args()

    cid, display_name, evaluations = _load_client_evaluations(args.client)
    idx, ev = _pick_evaluation(evaluations, args.row, args.account)
    row_no = idx + 3

    acc = str(ev.get("Account #") or ev.get("Account #.1") or ev.get("Account") or "-").strip()
    firm = str(ev.get("Prop Firm") or "-").strip()
    status_p1 = str(ev.get("Status P1") or "").strip()
    status_fd = str(ev.get("Status") or ev.get("Status Funded") or "").strip()

    p1_total, p1_parts = _sum_cols(ev, P1_HEDGE_COLS)
    fd_total, fd_parts = _sum_cols(ev, FUNDED_HEDGE_COLS)
    if args.phase == "evaluation":
        total_hedge = p1_total
    elif args.phase == "funded":
        total_hedge = fd_total
    else:
        total_hedge = round(p1_total + fd_total, 2)

    print(f"Client: {display_name}  (client_id={cid})")
    print(f"Row: {row_no}  (idx={idx})")
    print(f"Account: {acc}")
    print(f"Prop Firm: {firm}")
    print(f"Status P1: {status_p1!r}   Status Funded: {status_fd!r}")
    print("")

    def _print_block(title: str, parts: List[Tuple[str, float, Any]], subtotal: float):
        print(title)
        print("-" * len(title))
        for c, val, raw in parts:
            raw_s = "" if raw is None else str(raw)
            print(f"{c:<16} {val:>10.2f}   raw={raw_s!r}")
        print(f"{'SUBTOTAL':<16} {subtotal:>10.2f}")
        print("")

    if args.phase in ("evaluation", "both"):
        _print_block("Phase 1 hedge results (Hedge Result 1..5)", p1_parts, p1_total)
    if args.phase in ("funded", "both"):
        _print_block("Funded hedge results (Hedge Result 1.1..5.1, 6, 7)", fd_parts, fd_total)

    label = "TOTAL hedging results"
    if args.phase == "evaluation":
        label = "TOTAL (evaluation phase hedges only)"
    elif args.phase == "funded":
        label = "TOTAL (funded phase hedges only)"
    print(f"{label}: {_money(total_hedge)}")

    # Show any related computed cells if present in the row
    for k in ("Hedge Net", "Hedge Net.1"):
        if k in ev:
            print(f"{k}: {ev.get(k)!r} (parsed={parse_currency(ev.get(k)):.2f})")

    if args.expected is not None:
        exp = round(float(args.expected), 2)
        ok = abs(exp - total_hedge) < 0.005
        print("")
        print(f"Expected (dashboard): {_money(exp)}")
        print(f"Computed:            {_money(total_hedge)}")
        print(f"Match:              {'YES' if ok else 'NO'}  (delta={_money(total_hedge - exp)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

