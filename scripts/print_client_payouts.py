"""
Print all payouts for a single client from the database.

Looks inside `clients_data.evaluations` JSON for keys like:
  - Payout 1..10
  - Date 1..10

Examples:
  python scripts/print_client_payouts.py --client "Thak Mano"
  python scripts/print_client_payouts.py --client "Thak Mano" --include-kyc
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    # Postgres connector (requires psycopg2 installed)
    from dashboard.database import get_connection, get_all_kyc_accounts  # type: ignore
except ModuleNotFoundError as e:  # pragma: no cover
    missing = str(e).split("No module named", 1)[-1].strip().strip(":").strip().strip("'").strip('"')
    raise SystemExit(
        "Missing Postgres dependency.\n"
        f"Error: {e}\n\n"
        "Install it, then rerun:\n"
        "  pip install psycopg2-binary\n"
        "  # or: pip install psycopg2\n"
    ) from e
except Exception as e:  # pragma: no cover
    raise SystemExit(f"Failed to import Postgres database module: {e}") from e


def parse_currency(val: Any) -> float:
    """
    Lightweight currency parser (kept local to avoid importing pandas-heavy modules).
    Mirrors the project's intended behavior: unparseable strings count as 0.0.
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
                # treat comma-decimal endings as unparseable (Sheets SUM -> 0 on text)
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


_FIRM_MAP = {
    "mffu": "My Funded Futures",
    "mffuflex": "My Funded Futures",
    "myfundedfutures": "My Funded Futures",
    "myfundedfx": "My Funded Futures",
    "mff": "My Funded Futures",
    "topstep": "Topstep",
    "fundingticks": "Funding Ticks",
    "fundingtick": "Funding Ticks",
    "fundednext": "FundedNext",
    "tradeday": "TradeDay",
    "tradeify": "Tradeify",
    "alphafutures": "Alpha Futures",
    "ftmo": "FTMO",
    "blueguardian": "Blue Guardian",
    "fundedtradingplus": "Funded Trading Plus",
    "the5ers": "The 5%ers",
    "apextraderfunding": "Apex Trader Funding",
    "apextrader": "Apex Trader Funding",
    "uprofittrader": "UProfit",
    "uprofit": "UProfit",
    "bulenox": "Bulenox",
    "tickticktrader": "TickTick Trader",
    "elitetraderfunding": "Elite Trader Funding",
    "takeprofittrader": "Take Profit Trader",
    "lucid": "Lucid",
    "toponefutures": "Top One Futures",
    "topone": "Top One Futures",
}


def normalize_prop_firm(name: Any) -> str:
    if not name:
        return "Unknown"
    original = str(name).strip()
    key = original.lower().replace(" ", "").replace("_", "")
    if key in _FIRM_MAP:
        return _FIRM_MAP[key]
    if "myfundedfutures" in key or "myfundedfx" in key:
        return "My Funded Futures"
    if "fundednext" in key:
        return "FundedNext"
    if "topstep" in key:
        return "Topstep"
    if "fundingtick" in key:
        return "Funding Ticks"
    return original


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _write_html_report(path: str, title: str, subtitle: str, table_html: str, totals_html: str) -> str:
    css = """
    :root { --bg:#0b1020; --card:#111a33; --text:#e8ecff; --muted:#aeb8e6; --grid:#243055; --accent:#7aa2ff; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1200px; margin: 28px auto; padding: 0 18px 40px; }
    .head { display:flex; gap:16px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; }
    h1 { margin:0; font-size: 22px; letter-spacing: .2px; }
    .sub { margin:6px 0 0; color:var(--muted); font-size: 13px; }
    .card { background: var(--card); border:1px solid var(--grid); border-radius: 14px; padding: 14px 16px; }
    .cards { display:grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 12px; margin-top: 14px; }
    .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .v { font-size: 20px; margin-top: 6px; }
    .tablewrap { margin-top: 14px; overflow:auto; border-radius: 14px; border:1px solid var(--grid); }
    table { width:100%; border-collapse: collapse; background: var(--card); }
    th, td { padding: 10px 10px; border-bottom: 1px solid var(--grid); font-size: 13px; white-space: nowrap; }
    th { position: sticky; top:0; background: #0f1834; color: var(--muted); text-align:left; font-weight: 600; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    .badge { display:inline-block; padding: 3px 8px; border-radius: 999px; background: rgba(122,162,255,.12); border:1px solid rgba(122,162,255,.35); color: var(--text); font-size: 12px; }
    a { color: var(--accent); text-decoration: none; }
    """
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div>
        <h1>{html.escape(title)}</h1>
        <div class="sub">{html.escape(subtitle)}</div>
      </div>
      <div class="badge">Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
    </div>

    <div class="cards">
      {totals_html}
    </div>

    <div class="tablewrap">
      {table_html}
    </div>
  </div>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return os.path.abspath(path)


def _fetch_clients_rows() -> List[Dict[str, Any]]:
    """
    Fetch `client_id`, `identity`, `evaluations` rows from clients_data.
    Uses Postgres via project db module.
    """
    with get_connection() as conn:  # type: ignore[misc]
        cur = conn.cursor()
        cur.execute("SELECT client_id, identity, evaluations FROM clients_data")
        return cur.fetchall() or []


def _norm(s: Any) -> str:
    return str(s or "").strip().casefold()


def _parse_date_maybe(date_str: Any) -> Optional[datetime]:
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.strip()
    if not s or s in ("-", "n/a", "null"):
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class PayoutRow:
    client_id: str
    client_name: str
    prop_firm: str
    account: str
    payout_no: int
    date_raw: str
    date_obj: Optional[datetime]
    amount: float


def _iter_payouts_for_evaluations(
    client_id: str,
    client_name: str,
    evaluations: Iterable[Dict[str, Any]],
) -> Iterable[PayoutRow]:
    for ev in evaluations:
        if not isinstance(ev, dict):
            continue

        firm = normalize_prop_firm(ev.get("Prop Firm"))
        account = str(ev.get("Account #") or ev.get("Account #.1") or ev.get("Account") or "-").strip()

        for i in range(1, 11):
            amount = parse_currency(ev.get(f"Payout {i}"))
            if amount <= 0:
                continue
            date_raw = str(ev.get(f"Date {i}") or "").strip()
            date_obj = _parse_date_maybe(date_raw)
            yield PayoutRow(
                client_id=client_id,
                client_name=client_name,
                prop_firm=firm or "Unknown",
                account=account or "-",
                payout_no=i,
                date_raw=date_raw or "-",
                date_obj=date_obj,
                amount=float(amount),
            )


def _load_matching_client_rows(target_client: str) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
    """
    Returns a list of tuples: (client_id, display_name, evaluations_list)
    Matching is case-insensitive against:
      - clients_data.client_id
      - clients_data.identity JSON field "name"
    """
    wanted = _norm(target_client)
    matches: List[Tuple[str, str, List[Dict[str, Any]]]] = []
    rows = _fetch_clients_rows()

    for row in rows:
        client_id = str(row.get("client_id") or "").strip()
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

        if _norm(client_id) == wanted or _norm(identity_name) == wanted:
            display_name = identity_name or client_id
            matches.append((client_id, display_name, evaluations))

    return matches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help='Client name to match (e.g. "Thak Mano")')
    ap.add_argument(
        "--include-kyc",
        action="store_true",
        help="If client is KYC-linked, include payouts for linked accounts too.",
    )
    ap.add_argument(
        "--html",
        nargs="?",
        const="",
        default=None,
        help="Write an HTML report (optional path; default: reports/<client>-payouts.html).",
    )
    args = ap.parse_args()

    client_rows = _load_matching_client_rows(args.client)
    if not client_rows:
        print(f"No client match found for: {args.client!r}")
        return 2

    # If multiple matches exist (rare), print them all (unless KYC is used, where we expand anyway)
    client_ids = [cid for (cid, _name, _evals) in client_rows]
    if args.include_kyc:
        expanded: List[str] = []
        for cid, name, _evals in client_rows:
            # Prefer expanding from the display name (often the "real" client name),
            # but fall back to cid if needed.
            base = name or cid
            try:
                expanded.extend(get_all_kyc_accounts(base))
            except Exception:
                expanded.append(base)
        # Deduplicate, keep stable order
        seen = set()
        expanded_unique = []
        for x in expanded:
            nx = str(x).strip()
            if nx and nx not in seen:
                seen.add(nx)
                expanded_unique.append(nx)
        # Reload using expanded names so we pick up any that are stored under different client_id/identity
        reloaded: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        for name in expanded_unique:
            reloaded.extend(_load_matching_client_rows(name))
        # Deduplicate by client_id
        dedup = {}
        for cid, name, evals in reloaded:
            dedup[cid] = (cid, name, evals)
        client_rows = list(dedup.values())
        client_ids = [cid for (cid, _name, _evals) in client_rows]

    payouts: List[PayoutRow] = []
    for cid, display_name, evals in client_rows:
        payouts.extend(list(_iter_payouts_for_evaluations(cid, display_name, evals)))

    # Sort: date desc first; unknown dates last
    payouts.sort(
        key=lambda r: (
            0 if r.date_obj else 1,
            r.date_obj or datetime.min,
        ),
        reverse=True,
    )

    header = f"Payouts for: {args.client}  (matched client_id(s): {', '.join(client_ids)})"
    subtitle = f"Matched client_id(s): {', '.join(client_ids)}"
    print(header)
    print("-" * max(60, len(header)))

    if not payouts:
        print("No payouts found (no positive Payout 1..10 values in evaluations).")
        return 0

    total = 0.0
    print(f"{'Date':<12} {'Amount':>12}  {'Firm':<22}  {'Account':<12}  {'#':>2}  {'Client':<20}")
    print("-" * 95)
    for r in payouts:
        total += r.amount
        date_out = (r.date_obj.strftime("%Y-%m-%d") if r.date_obj else r.date_raw)[:12]
        print(
            f"{date_out:<12} ${r.amount:>10,.2f}  {r.prop_firm[:22]:<22}  {r.account[:12]:<12}  {r.payout_no:>2}  {r.client_name[:20]:<20}"
        )

    print("-" * 95)
    print(f"Total payouts: ${total:,.2f}   (count: {len(payouts)})")

    if args.html is not None:
        out = args.html
        if out == "":
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(args.client).strip()).strip("-") or "client"
            reports_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "reports")
            os.makedirs(reports_dir, exist_ok=True)
            out = os.path.join(reports_dir, f"{safe}-payouts.html")

        rows_html = []
        for r in payouts:
            date_out = (r.date_obj.strftime("%Y-%m-%d") if r.date_obj else r.date_raw)[:32]
            rows_html.append(
                "<tr>"
                f"<td>{html.escape(date_out or '-')}</td>"
                f"<td class='num'>{html.escape(_money(r.amount))}</td>"
                f"<td>{html.escape(r.prop_firm)}</td>"
                f"<td>{html.escape(r.account)}</td>"
                f"<td class='num'>{r.payout_no}</td>"
                f"<td>{html.escape(r.client_name)}</td>"
                "</tr>"
            )

        table_html = (
            "<table>"
            "<thead><tr>"
            "<th>Date</th><th class='num'>Amount</th><th>Firm</th><th>Account</th><th class='num'>#</th><th>Client</th>"
            "</tr></thead>"
            "<tbody>"
            + "".join(rows_html)
            + "</tbody></table>"
        )
        totals_html = (
            f"<div class='card'><div class='k'>Total payouts</div><div class='v'>{html.escape(_money(total))}</div></div>"
            f"<div class='card'><div class='k'>Payout count</div><div class='v'>{len(payouts):,}</div></div>"
            f"<div class='card'><div class='k'>Report</div><div class='v'>Payouts</div><div class='sub'>{html.escape(args.client)}</div></div>"
        )
        abs_out = _write_html_report(out, f"Payouts — {args.client}", subtitle, table_html, totals_html)
        print(f"\nHTML written: {abs_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

