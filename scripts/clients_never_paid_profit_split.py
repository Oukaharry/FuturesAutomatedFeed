#!/usr/bin/env python3
"""
List clients who have never received a profit split.

A client qualifies when every row in their computed Profit Share History has
profit_split = $0 (no period has ever paid a split).

Usage:
    python scripts/clients_never_paid_profit_split.py
    python scripts/clients_never_paid_profit_split.py --pdf
    python scripts/clients_never_paid_profit_split.py --pdf --output reports/never_paid_splits.pdf
    python scripts/clients_never_paid_profit_split.py --json report.json
    python scripts/clients_never_paid_profit_split.py --txt
    python scripts/clients_never_paid_profit_split.py --txt reports/names_only.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from dashboard.database import get_connection
from dashboard.watermark_service import compute_waterlog_from_db


def _parse_money(value) -> float:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text or text.lower() == "nan":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _load_renderer():
    pdf_helper = ROOT / "_render_report_pdf.py"
    if not pdf_helper.is_file():
        raise SystemExit(
            f"Missing {pdf_helper.name} in repo root.\n"
            "Copy the local gitignored PDF helper into the project root "
            "(it is not tracked in git)."
        )
    try:
        from _render_report_pdf import render_report_pdf
    except ImportError as exc:
        if exc.name == "reportlab" or "reportlab" in str(exc):
            raise SystemExit(
                "PDF generation requires reportlab.\n"
                "Install it in your venv:  pip install reportlab"
            ) from exc
        raise SystemExit(
            f"Could not import {pdf_helper.name}: {exc}\n"
            "Ensure reportlab is installed:  pip install reportlab"
        ) from exc
    return render_report_pdf


def collect_clients_never_paid() -> list[dict]:
    rows: list[dict] = []

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT client_id FROM clients_data ORDER BY client_id ASC")
        client_ids = [r["client_id"] for r in cursor.fetchall()]

    for client_id in client_ids:
        waterlog = compute_waterlog_from_db(client_id)
        if not waterlog:
            continue
        periods = waterlog.get("periods") or []
        if not periods:
            continue
        if any(_parse_money(p.get("profit_split")) > 0 for p in periods):
            continue

        latest = periods[-1]
        rows.append(
            {
                "client_id": client_id,
                "period_count": len(periods),
                "latest_period_end": (latest.get("to_date") or "").strip(),
                "latest_net_profit": (latest.get("low") or "$0").strip(),
                "latest_split_pct": latest.get("split_pct", 50),
                "source": waterlog.get("_source", "db"),
            }
        )

    return rows


def build_report_payload(rows: list[dict]) -> dict:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "title": "Clients Who Have Never Received a Profit Split",
        "subtitle": f"Generated {generated} · {len(rows)} client(s)",
        "summary": [
            "These clients have computed Profit Share History rows, but every period shows $0 profit split.",
        ],
        "tables": [
            {
                "title": "Client summary",
                "headers": ["#", "Client", "Periods", "Latest period end", "Latest net profit", "Split %"],
                "col_widths": [0.35, 2.0, 0.65, 1.2, 1.2, 0.55],
                "rows": [
                    [
                        str(i),
                        r["client_id"],
                        str(r["period_count"]),
                        r["latest_period_end"],
                        r["latest_net_profit"],
                        f"{int(r['latest_split_pct'])}%",
                    ]
                    for i, r in enumerate(rows, start=1)
                ],
            }
        ],
        "footer": "Source: dashboard DB (waterlog_periods + daily_watermarks via compute_waterlog_from_db).",
    }


def write_names_file(rows: list[dict], path: Path) -> Path:
    """Plain text, numbered client names one per line (Notepad-friendly CRLF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{i}. {r['client_id']}" for i, r in enumerate(rows, start=1)]
    body = "\r\n".join(lines)
    if body:
        body += "\r\n"
    path.write_text(body, encoding="utf-8")
    return path


def print_table(rows: list[dict]) -> None:
    print(f"{'#':>3}  {'Client':<32} {'Periods':>7}  {'Period end':<12}  {'Net profit':>14}")
    print("-" * 78)
    for i, r in enumerate(rows, start=1):
        print(
            f"{i:>3}  {r['client_id']:<32} {r['period_count']:>7}  "
            f"{r['latest_period_end']:<12}  {r['latest_net_profit']:>14}"
        )
    print(f"\nTotal: {len(rows)} client(s) with all-zero profit splits.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report clients whose Profit Share History has never paid a split."
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Write a PDF via repo-root _render_report_pdf.py",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Write the report payload JSON to this path",
    )
    parser.add_argument(
        "--txt",
        "--names",
        nargs="?",
        const=str(ROOT / "reports" / "clients_never_paid_profit_split.txt"),
        metavar="PATH",
        dest="txt",
        help="Write client names only (one per line) for Notepad. Default: reports/clients_never_paid_profit_split.txt",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(ROOT / "reports" / "clients_never_paid_profit_split.pdf"),
        help="PDF output path (with --pdf)",
    )
    args = parser.parse_args()

    rows = collect_clients_never_paid()
    report = build_report_payload(rows)
    wrote_output = False

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {json_path.resolve()}")
        wrote_output = True

    if args.txt is not None:
        txt_path = write_names_file(rows, Path(args.txt))
        print(f"Wrote {len(rows)} name(s) -> {txt_path.resolve()}")
        wrote_output = True

    if args.pdf:
        render_report_pdf = _load_renderer()
        out = render_report_pdf(report, args.output)
        print(f"Wrote {out.resolve()}")
        wrote_output = True

    if not wrote_output:
        print_table(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
