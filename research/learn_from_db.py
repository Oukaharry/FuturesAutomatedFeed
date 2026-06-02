#!/usr/bin/env python3
"""
Fetch stored MT5 deals from clients_data, analyze, and write an HTML report.

Usage (from project root):
    python research/learn_from_db.py
    python research/learn_from_db.py --production
    python research/learn_from_db.py --client "Chris Ream"
    python research/learn_from_db.py --out research/reports/analysis.html
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")

DEFAULT_OUT = os.path.join(_ROOT, "research", "reports", "mt5_analysis.html")


def run_learning(
    client_filter: str | None = None,
    *,
    production: bool = False,
    database_url: str | None = None,
) -> tuple[str, str]:
    """Returns (html_content, data_source_description)."""
    from research.collect_analysis import collect_analysis
    from research.db_source import run_learning_with_source
    from research.html_report import render_html

    def _collect():
        return collect_analysis(client_filter)

    data, _kind, desc = run_learning_with_source(
        _collect,
        production=production,
        database_url=database_url,
    )
    html = render_html(data, data_source_line=desc)
    return html, desc


def main():
    ap = argparse.ArgumentParser(
        description="MT5 deal analysis → HTML report. Use --production for live Postgres."
    )
    ap.add_argument("--client", help="Limit to one client_id")
    ap.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"HTML output path (default: {DEFAULT_OUT})",
    )
    ap.add_argument("--production", action="store_true", help="SSH tunnel to production DB")
    ap.add_argument("--database-url", help="Override DB URL (e.g. restored backup)")
    args = ap.parse_args()
    if args.production and args.database_url:
        ap.error("Use only one of --production or --database-url")

    out = args.out
    if out and not out.lower().endswith(".html"):
        out = os.path.splitext(out)[0] + ".html"

    html, desc = run_learning(
        args.client,
        production=args.production,
        database_url=args.database_url,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(desc)
    print(f"Wrote HTML report: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
