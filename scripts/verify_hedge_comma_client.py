"""
verify_hedge_comma_client.py
-----------------------------
Verify the "Comma in hedge value" quality flag against the live `clients_data` JSON.

The dashboard's run_quality_scan() only flags values where:
  - Column starts with "Hedge Result" or "Hedge Day"
  - The cell contains a comma, has NO '.' in the value (after stripping $), and
  - The value matches ",NN" at the end (European decimal style), e.g. -155,79

Quality "Row N" is the Nth entry in the `evaluations` JSON array (1-based). That often does
not match Google Sheet row numbers (header rows, filters, sort order, or rows only in DB).

Use this script's hit list and `--find` to match by value or account — not by row index.

If the value no longer exists but the issue still shows, the likely cause is a *stale*
saved quality scan: GET /api/quality/client/<id> without ?rescan=1 loads the latest
`quality_scan_results` batch, not a live re-scan.

Usage (from repo root, DATABASE_URL set to your DB):
  python scripts/verify_hedge_comma_client.py
  python scripts/verify_hedge_comma_client.py "Anthony Arnold"
  python scripts/verify_hedge_comma_client.py "Anthony Arnold" --find "-155,79"
  python scripts/verify_hedge_comma_client.py "Anthony Arnold" --row 42   # optional: one 1-based index
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any

# Repo root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.chdir(_ROOT)

from dashboard.database import get_client_data, get_connection, get_quality_scan_results  # noqa: E402


def _row_passes_scan_preamble(ev: dict) -> bool:
    """Match run_quality_scan: rows skipped before per-field checks (same as app)."""
    if ev.get("_deleted"):
        return False
    status_p1 = str(ev.get("Status P1", "") or "").strip().lower()
    status_p2 = str(ev.get("Status", "") or "").strip().lower()
    if "delete" in status_p1 or "delete" in status_p2:
        return False
    prop_firm = str(ev.get("Prop Firm", "") or "").strip()
    acct_size = str(ev.get("Account Size", "") or "").strip()
    has_data = bool(prop_firm or acct_size)
    if not has_data:
        return False
    if prop_firm.lower() in ("funding ticks", "fundingticks"):
        return False
    return True


def _comma_in_hedge_flagged(_col: str, _val: str) -> bool:
    """Same logic as dashboard/app.py run_quality_scan (Comma in hedge value)."""
    if not isinstance(_col, str) or not (
        _col.startswith("Hedge Result") or _col.startswith("Hedge Day")
    ):
        return False
    s = str(_val or "").strip()
    if not s or "," not in s:
        return False
    probe = s.replace("$", "").strip()
    if "." in probe:
        return False
    if re.search(r",\d{2}\s*$", probe):
        return True
    return False


def _all_comma_mentions(ev: dict) -> list[tuple[str, str]]:
    """Any Hedge Result / Hedge Day cell containing a comma (looser than the flag)."""
    out: list[tuple[str, str]] = []
    for k, v in ev.items():
        if not isinstance(k, str):
            continue
        if not (k.startswith("Hedge Result") or k.startswith("Hedge Day")):
            continue
        s = str(v or "").strip()
        if "," in s:
            out.append((k, s))
    return out


def _ident(ev: dict) -> str:
    """Short line to match a DB row to a sheet without relying on row number."""
    parts = [
        str(ev.get("Prop Firm", "") or "").strip() or "?",
        str(ev.get("Account #", "") or "").strip() or "-",
        str(ev.get("Account #.1", "") or "").strip() or "",
        str(ev.get("Date Started", "") or "").strip() or "",
    ]
    tail = " / ".join(p for p in parts[1:] if p)
    return f"{parts[0]} | {tail}" if tail else parts[0]


def _find_substring(evs: list, needle: str) -> list[tuple[int, str, str, str]]:
    """Rows where any Hedge Result / Hedge Day cell contains `needle` (case-sensitive)."""
    out: list[tuple[int, str, str, str]] = []
    if not needle:
        return out
    for idx, ev in enumerate(evs):
        if not isinstance(ev, dict):
            continue
        for k, v in ev.items():
            if not isinstance(k, str):
                continue
            if not (k.startswith("Hedge Result") or k.startswith("Hedge Day")):
                continue
            s = str(v or "")
            if needle in s:
                out.append((idx, k, s.strip(), _ident(ev)))
    return out


def _load_saved_comma_issues(client_id: str) -> list[dict[str, Any]]:
    rows = get_quality_scan_results() or []
    for r in rows:
        if r.get("client_id") == client_id:
            return [
                i
                for i in (r.get("issues") or [])
                if i.get("check") == "Comma in hedge value"
            ]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify hedge comma quality flags vs clients_data")
    ap.add_argument("client", nargs="?", default="Anthony Arnold", help="client_id in clients_data")
    ap.add_argument(
        "--row",
        type=int,
        default=None,
        metavar="N",
        help="optional: dump one 1-based evaluations[] index (often ≠ sheet row)",
    )
    ap.add_argument(
        "--find",
        default="",
        metavar="TEXT",
        help="search Hedge Result / Hedge Day cells for this substring (e.g. -155,79 or ,79)",
    )
    args = ap.parse_args()
    client_id = args.client
    one_based = args.row
    zero = (one_based - 1) if one_based is not None else None

    print(f"DATABASE_URL: {os.environ.get('DATABASE_URL', '(default from .env)')[:60]}…")
    print(f"Client: {client_id!r}\n")

    data = get_client_data(client_id)
    if not data:
        print("No row in clients_data for this client_id.")
        return 1

    evs: list[dict] = data.get("evaluations") or []
    print(
        f"evaluations: {len(evs)} rows in DB (quality 'Row N' = index N-1 in this list; "
        "sheet row numbers often differ).\n"
    )

    # Strict matches (as quality scan)
    strict_hits: list[tuple[int, str, str]] = []
    # Loose: any comma in hedge columns
    loose_hits: list[tuple[int, str, str]] = []

    for idx, ev in enumerate(evs):
        if not isinstance(ev, dict):
            continue
        if not _row_passes_scan_preamble(ev):
            continue
        for k, v in ev.items():
            if _comma_in_hedge_flagged(k, str(v)):
                strict_hits.append((idx, k, str(v).strip()))
        for k, s in _all_comma_mentions(ev):
            loose_hits.append((idx, k, s))

    print("--- Live DB: strict 'Comma in hedge value' matches (same rules as app) ---")
    if not strict_hits:
        print("  (none)\n")
    else:
        for idx, k, s in strict_hits:
            ev = evs[idx] if isinstance(evs[idx], dict) else {}
            print(f"  Row {idx + 1} (idx={idx}): {k} = {s!r}")
            print(f"      {_ident(ev)}")
        print()

    if loose_hits and not strict_hits:
        print("--- Cells with a comma in Hedge Result / Hedge Day (looser) ---")
        for idx, k, s in loose_hits:
            probe = s.replace("$", "").strip()
            reason = []
            if "." in probe:
                reason.append("has '.'  US-style → not flagged")
            elif not re.search(r",\d{2}\s*$", probe):
                reason.append("comma not at end as ,NN → not flagged")
            print(f"  Row {idx + 1}: {k} = {s!r}  ({'; '.join(reason) or 'n/a'})")
        print()

    if args.find:
        print(f"--- --find {args.find!r}: Hedge Result / Hedge Day substring matches ---")
        found = _find_substring(evs, args.find)
        if not found:
            print("  (none)\n")
        else:
            for idx, k, s, ident in found:
                print(f"  Row {idx + 1}: {k} = {s!r}")
                print(f"      {ident}")
            print()

    # Optional single index (evaluations array position — not sheet row)
    if one_based is not None:
        assert zero is not None
        print(f"--- Optional --row {one_based} (evaluations index {zero}) ---")
        if zero < 0 or zero >= len(evs):
            print(f"  Out of range (have {len(evs)} rows).")
        else:
            ev = evs[zero]
            if not isinstance(ev, dict):
                print(f"  evaluations[{zero}] is not a dict: {type(ev)}")
            else:
                print(f"  {_ident(ev)}")
                hr2 = ev.get("Hedge Result 2")
                print(f"  Hedge Result 2 raw: {hr2!r}  (type: {type(hr2).__name__})")
                if isinstance(hr2, (int, float)):
                    print(
                        "  Note: value is numeric in JSON. No comma in storage; the UI may format it."
                    )
                flagged = _comma_in_hedge_flagged("Hedge Result 2", str(hr2))
                preamble = _row_passes_scan_preamble(ev)
                print(f"  Row would pass quality-scan preamble: {preamble}")
                print(f"  'Comma in hedge value' would flag HR2: {flagged and preamble}")
        print()

    print("\n--- Saved quality scan (latest batch in quality_scan_results) ---")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(scan_date) AS d FROM quality_scan_results")
            drow = cur.fetchone()
            max_date = drow["d"] if drow else None
        print(f"  Latest scan_date: {max_date}")
    except Exception as e:
        print(f"  (could not read scan_date: {e})")

    saved = _load_saved_comma_issues(client_id)
    if not saved:
        print("  No 'Comma in hedge value' in saved results for this client (or no saved scan).")
    else:
        for i, issue in enumerate(saved, 1):
            print(f"  [{i}] {issue.get('detail')!r}  row_idx={issue.get('row')}")
            print(f"      estimated_date: {issue.get('estimated_date')}")

    # Diagnosis
    print("\n--- Diagnosis ---")
    if strict_hits:
        print(
            "The value still exists under the same rules the scanner uses. "
            "Re-scan the client with ?rescan=1 to refresh stored issues."
        )
    else:
        print(
            "Current DB data does NOT contain any value that would trigger "
            "'Comma in hedge value' with the app rules."
        )
        if saved:
            print(
                "A saved quality_scan_results record still lists this issue — typical reasons:\n"
                "  * Data was corrected after the last global scan, but the dashboard showed cached results.\n"
                "  * Open the Data Quality panel with rescan=1 (Refresh) to persist today's live scan.\n"
                "  * Sheet row # ≠ quality Row N: the scanner uses JSON array order only.\n"
                "  * You may have been comparing Google Sheets → CSV: source of truth for the flag is `clients_data.evaluations` in PostgreSQL."
            )
        else:
            print("No saved comma issue for this client; if the UI still shows it, try a hard refresh / rescan.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
