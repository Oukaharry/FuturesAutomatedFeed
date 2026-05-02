#!/usr/bin/env python3
"""
List quality-scan issues for one client in a readable terminal table.

Usage:
  python scripts/list_client_quality_issues.py Dennick
  python scripts/list_client_quality_issues.py "Brian Shore" --date 2026-05-01
  python scripts/list_client_quality_issues.py Dennick --fresh

Run from the project root (directory containing config/ and dashboard/), with the
same Python environment you use for the dashboard (PostgreSQL / psycopg2 required).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from typing import Any, List, Optional, Sequence, Tuple

# Project root on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")


def _resolve_client_id(query: str) -> str:
    from config.hierarchy import get_all_clients, get_client_profile

    q = (query or "").strip()
    if not q:
        sys.exit("Pass a client name as the first argument.")

    clients = get_all_clients()
    if not clients:
        sys.exit("No clients defined in hierarchy.")

    lower = q.lower()
    # Exact case-sensitive match
    for c in clients:
        if c == q:
            return c
    # Case-insensitive exact
    for c in clients:
        if c.lower() == lower:
            return c
    # Unique substring match (client id contains query)
    subs = [c for c in clients if lower in c.lower()]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        sys.exit(
            "Ambiguous client query; multiple matches:\n  "
            + "\n  ".join(subs[:25])
            + (f"\n  … ({len(subs)} total)" if len(subs) > 25 else "")
        )
    # Match trader name (exact / substring) — one client per trader is common in small teams
    by_trader: List[str] = []
    for c in clients:
        prof = get_client_profile(c) or {}
        t = str(prof.get("trader") or "").strip().lower()
        if t and (t == lower or lower in t):
            by_trader.append(c)
    if len(by_trader) == 1:
        return by_trader[0]
    if len(by_trader) > 1:
        sys.exit(
            "Ambiguous: trader name matches multiple clients:\n  "
            + "\n  ".join(by_trader)
        )

    sys.exit(
        f"No client matches {q!r}.\n"
        f"Try an exact hierarchy client name. Example names: {', '.join(sorted(clients)[:8])}"
        + (" …" if len(clients) > 8 else "")
    )


def _trunc(s: Any, width: int) -> str:
    t = "" if s is None else str(s).replace("\n", " ").replace("\r", " ")
    t = t.strip()
    if len(t) <= width:
        return t
    if width <= 1:
        return "…"
    return t[: width - 1] + "…"


def _border(widths: Sequence[int], left: str, mid: str, right: str) -> str:
    return left + mid.join("─" * (w + 2) for w in widths) + right


def _row_line(cells: Sequence[str], col_widths: Sequence[int]) -> str:
    parts = []
    for cell, w in zip(cells, col_widths):
        parts.append(f" {str(cell).ljust(w)} │")
    return "│" + "".join(parts)


def _print_table(
    *,
    client_id: str,
    scan_date: Optional[str],
    health: Any,
    trader: str,
    admin: str,
    issues: List[dict],
    detail_width: int,
) -> None:
    # Column widths: #, check, sev, row, est_date, detail
    w_num, w_chk, w_sev, w_row, w_est = 3, 28, 10, 5, 12
    w_det = max(24, detail_width)

    headers = ("#", "Check", "Severity", "Row", "Est. date", "Detail")
    widths = (w_num, w_chk, w_sev, w_row, w_est, w_det)
    inner = len(_border(widths, "┌", "┬", "┐"))

    title = f" Quality issues — {client_id} "
    sub = []
    if scan_date:
        sub.append(f"scan {scan_date}")
    if health is not None:
        sub.append(f"health {health}")
    sub.append(f"{len(issues)} issue(s)")
    sub2 = f" Trader: {trader or '—'}  │  Admin: {admin or '—'} "

    body_lines: List[str] = []
    for i, iss in enumerate(issues, start=1):
        chk = str(iss.get("check") or "")
        sev = str(iss.get("severity") or "")
        row = iss.get("row")
        row_s = "" if row is None else str(row)
        est = str(iss.get("estimated_date") or "")
        det = str(iss.get("detail") or "")

        det_chunks = textwrap.wrap(det, width=w_det, break_long_words=True, break_on_hyphens=False)
        if not det_chunks:
            det_chunks = [""]

        first = True
        for chunk in det_chunks:
            c_num = str(i) if first else ""
            c_chk = _trunc(chk, w_chk) if first else ""
            c_sev = _trunc(sev, w_sev) if first else ""
            c_row = _trunc(row_s, w_row) if first else ""
            c_est = _trunc(est, w_est) if first else ""
            cells = (
                _trunc(c_num, w_num),
                c_chk,
                c_sev,
                c_row,
                c_est,
                _trunc(chunk, w_det),
            )
            body_lines.append(_row_line(cells, widths))
            first = False

    top_pad = max(0, (inner - len(title)) // 2)
    banner = "═" * inner

    print()
    print(f"\033[36m{banner}\033[0m")
    print("\033[1;36m" + " " * top_pad + title + "\033[0m")
    print(f"\033[90m  {'  ·  '.join(sub)}\033[0m")
    print(f"\033[90m{sub2}\033[0m")
    print(f"\033[36m{banner}\033[0m")

    print(_border(widths, "┌", "┬", "┐"))
    hdr_cells = tuple(headers[j].ljust(widths[j]) for j in range(len(headers)))
    print(_row_line(hdr_cells, widths))
    print(_border(widths, "├", "┼", "┤"))
    if not body_lines:
        print(
            _row_line(
                ("", "", "", "", "", "(no issues for this client on this scan)"),
                widths,
            )
        )
    else:
        for ln in body_lines:
            print(ln)
    print(_border(widths, "└", "┴", "┘"))
    print()


def _load_saved(client_id: str, scan_date: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
    try:
        from dashboard.database import get_quality_scan_results
    except ImportError as e:
        sys.exit(
            f"Cannot import dashboard.database ({e}). "
            "Activate the project virtualenv and install dependencies (e.g. psycopg2-binary)."
        )

    rows = get_quality_scan_results(scan_date)
    if not rows:
        return None, scan_date or None
    use_date = rows[0].get("scan_date") if rows else scan_date
    for r in rows:
        if str(r.get("client_id") or "") == client_id:
            return r, use_date
    return None, use_date


def _run_fresh(client_id: str) -> dict:
    from dashboard.app import run_quality_scan

    out = run_quality_scan(target_client=client_id)
    if not out:
        sys.exit("run_quality_scan returned no result.")
    return out[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Print quality-scan issues for one client (pretty table).")
    ap.add_argument("client", help="Client name or substring (hierarchy client id), e.g. Dennick")
    ap.add_argument("--date", metavar="YYYY-MM-DD", help="Use saved scan for this date (default: latest in DB)")
    ap.add_argument("--fresh", action="store_true", help="Run a live quality scan (imports full app; slower)")
    ap.add_argument("--detail-width", type=int, default=56, metavar="N", help="Width of the Detail column (default 56)")
    args = ap.parse_args()

    client_id = _resolve_client_id(args.client)
    scan_date = args.date
    rec: Optional[dict] = None
    used_date: Optional[str] = None

    if args.fresh:
        rec = _run_fresh(client_id)
        used_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    else:
        rec, used_date = _load_saved(client_id, scan_date)
        if rec is None:
            hint = (
                f"No saved scan row for client {client_id!r}"
                + (f" on {scan_date}" if scan_date else "")
                + ".\nTry: python scripts/list_client_quality_issues.py "
                + json.dumps(client_id)
                + " --fresh"
            )
            sys.exit(hint)

    from config.hierarchy import get_client_profile

    prof = get_client_profile(client_id) or {}
    issues = list(rec.get("issues") or [])
    _print_table(
        client_id=client_id,
        scan_date=used_date or rec.get("scan_date"),
        health=rec.get("health_score"),
        trader=str(prof.get("trader") or rec.get("trader") or ""),
        admin=str(prof.get("admin") or rec.get("admin") or ""),
        issues=issues,
        detail_width=args.detail_width,
    )


if __name__ == "__main__":
    main()
