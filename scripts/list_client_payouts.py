#!/usr/bin/env python3
"""
List all payouts for a client (by name), including account number + prop firm.

Works against either:
  - SQLite fallback (`dashboard/dashboard.db`) via `dashboard/db.py`, or
  - PostgreSQL if `DATABASE_URL` is set (same as the dashboard).

Usage:
  python scripts/list_client_payouts.py "Chris Ream"
  python scripts/list_client_payouts.py "Chris Ream" --csv payouts.csv
  python scripts/list_client_payouts.py "Chris Ream" --pretty
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _parse_currency(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "" or s == "-":
        return 0.0
    s = s.replace(",", "").replace("$", "").replace(" ", "")
    # common variants: "(123.45)" for negative
    m = re.fullmatch(r"\(([-+]?\d+(?:\.\d+)?)\)", s)
    if m:
        try:
            return -float(m.group(1))
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _parse_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == "-":
        return None

    # ISO-ish first (dashboard often stores isoformat strings)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass

    # Common spreadsheet-ish formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue

    return None


def _coerce_evaluations(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [ev for ev in raw if isinstance(ev, dict)]
    if isinstance(raw, str):
        raw_s = raw.strip()
        if not raw_s:
            return []
        try:
            data = json.loads(raw_s)
        except Exception:
            return []
        if isinstance(data, list):
            return [ev for ev in data if isinstance(ev, dict)]
    return []


def _load_evaluations_for_client(client_name: str, *, sqlite_db_path: str = "") -> Any:
    """
    Returns the raw `evaluations` payload for a client (string or list),
    using the best available DB access in the current environment.
    """
    # Ensure we can import `dashboard.*` when running from repo root
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    db_url = (os.environ.get("DATABASE_URL", "") or "").strip()
    prefer_postgres = db_url.lower().startswith("postgresql")

    # 1) Preferred path: SQLAlchemy session (works for SQLite + Postgres).
    try:
        from dashboard.db import SessionLocal  # type: ignore
        from dashboard.models import ClientsData  # type: ignore

        session = SessionLocal()
        try:
            row = (
                session.query(ClientsData)
                .filter(ClientsData.client_id == client_name)
                .first()
            )
            return getattr(row, "evaluations", None) if row else None
        finally:
            session.close()
    except ModuleNotFoundError:
        # common locally if requirements aren't installed (e.g. sqlalchemy, dotenv)
        pass
    except Exception:
        # If SQLAlchemy exists but DATABASE_URL is misconfigured, still try sqlite fallback.
        pass

    # 1b) Next best: psycopg2 wrapper used by the dashboard (PostgreSQL).
    # This avoids needing SQLAlchemy installed.
    try:
        from dashboard.database import get_connection  # type: ignore

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT evaluations FROM clients_data WHERE client_id = ?",
                (client_name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            # dashboard.database returns dict-like rows (RealDictCursor)
            if isinstance(row, dict) and "evaluations" in row:
                return row["evaluations"]
            # safety: some environments may return tuples
            try:
                return row[0]
            except Exception:
                return None
    except ModuleNotFoundError as e:
        if prefer_postgres and not sqlite_db_path and not os.environ.get("DASHBOARD_DB_PATH", "").strip():
            raise RuntimeError(
                "PostgreSQL DATABASE_URL is set but psycopg2 isn't available. "
                "Install deps or run with --db to point at SQLite."
            ) from e
    except Exception as e:
        if prefer_postgres and not sqlite_db_path and not os.environ.get("DASHBOARD_DB_PATH", "").strip():
            raise RuntimeError(
                f"PostgreSQL DATABASE_URL is set but connection failed: {e}"
            ) from e

    # 2) Fallback: direct sqlite3 read from dashboard/dashboard.db (or override)
    import sqlite3

    db_path = (
        sqlite_db_path.strip()
        or os.environ.get("DASHBOARD_DB_PATH", "").strip()
        or os.path.join(repo_root, "dashboard", "dashboard.db")
    )
    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        # fail fast if this isn't the right db file
        try:
            conn.execute("SELECT 1 FROM clients_data LIMIT 1").fetchone()
        except Exception:
            return None

        row = conn.execute(
            "SELECT evaluations FROM clients_data WHERE client_id=?",
            (client_name,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_client_payouts(client_name: str, *, sqlite_db_path: str = "") -> List[Dict[str, Any]]:
    """
    Returns list of payouts:
      {client, propfirm, account_number, payout_index, payout_amount, payout_date, source_row_index}
    """
    raw_evals = _load_evaluations_for_client(client_name, sqlite_db_path=sqlite_db_path)
    evals = _coerce_evaluations(raw_evals)
    if not evals:
        return []

    payouts: List[Dict[str, Any]] = []

    for idx, ev in enumerate(evals):
        if ev.get("_deleted"):
            continue

        propfirm = str(ev.get("Prop Firm", "") or "").strip()
        # Account number can be in either funded or eval column depending on row type.
        acct = (
            str(ev.get("Account #.1", "") or "").strip()
            or str(ev.get("Account #", "") or "").strip()
        )

        for i in range(1, 7):
            amt_raw = ev.get(f"Payout {i}")
            date_raw = ev.get(f"Date {i}")
            amt = _parse_currency(amt_raw)
            date_s = str(date_raw).strip() if date_raw is not None else ""

            if amt == 0.0 and (not date_s or date_s == "-"):
                continue

            payouts.append(
                {
                    "client": client_name,
                    "propfirm": propfirm,
                    "account_number": acct,
                    "payout_index": i,
                    "payout_amount": amt,
                    "payout_date": date_s,
                    "source_row_index": idx,
                }
            )

    # Sort by parsed date, then by amount desc (stable tie-breakers)
    def _sort_key(p: Dict[str, Any]) -> Tuple[int, datetime, float]:
        dt = _parse_date(p.get("payout_date"))
        if dt is None:
            return (1, datetime.min, -float(p.get("payout_amount") or 0.0))
        return (0, dt, -float(p.get("payout_amount") or 0.0))

    payouts.sort(key=_sort_key)
    return payouts


def _format_money(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        return str(x)
    return f"{v:,.2f}"


def _print_table(rows: List[Dict[str, Any]]) -> None:
    cols = [
        ("payout_date", "Payout Date"),
        ("payout_amount", "Payout"),
        ("propfirm", "Prop Firm"),
        ("account_number", "Account #"),
        ("payout_index", "#"),
        ("source_row_index", "Row"),
    ]

    def cell(row: Dict[str, Any], key: str) -> str:
        v = row.get(key, "")
        if key == "payout_amount":
            return _format_money(v)
        return "" if v is None else str(v)

    # Compute widths
    widths: Dict[str, int] = {}
    for key, header in cols:
        max_len = len(header)
        for r in rows:
            max_len = max(max_len, len(cell(r, key)))
        # cap ultra-wide columns for terminal readability
        widths[key] = min(max_len, 48)

    def clip(s: str, w: int) -> str:
        if len(s) <= w:
            return s
        if w <= 3:
            return s[:w]
        return s[: w - 3] + "..."

    # Header
    header = " | ".join(clip(h, widths[k]).ljust(widths[k]) for k, h in cols)
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for r in rows:
        line = " | ".join(
            clip(cell(r, k), widths[k]).ljust(widths[k]) for k, _h in cols
        )
        print(line)
    print(sep)
    print(f"{len(rows)} payouts")


def main() -> None:
    ap = argparse.ArgumentParser(description="List payouts for a client name")
    ap.add_argument("client_name", help='Client name / client_id (e.g. "Chris Ream")')
    ap.add_argument("--csv", dest="csv_path", default="", help="Write results to CSV file")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    ap.add_argument("--table", action="store_true", help="Print as a terminal table")
    ap.add_argument(
        "--db",
        dest="sqlite_db_path",
        default="",
        help="Path to SQLite db file (optional). Can also set DASHBOARD_DB_PATH env var.",
    )
    args = ap.parse_args()

    payouts = get_client_payouts(args.client_name, sqlite_db_path=args.sqlite_db_path)
    if not payouts:
        print(f"No payouts found (or client not found): {args.client_name}")
        sys.exit(1)

    if args.csv_path:
        fieldnames = [
            "client",
            "propfirm",
            "account_number",
            "payout_index",
            "payout_amount",
            "payout_date",
            "source_row_index",
        ]
        out_path = os.path.abspath(args.csv_path)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in payouts:
                w.writerow({k: row.get(k, "") for k in fieldnames})
        print(f"Wrote {len(payouts)} payout rows to {out_path}")
        return

    if args.table:
        _print_table(payouts)
        return

    if args.pretty:
        print(json.dumps(payouts, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payouts, ensure_ascii=False))


if __name__ == "__main__":
    main()

