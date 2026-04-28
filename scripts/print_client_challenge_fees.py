"""
Print all challenge fees for a single client from Postgres.

Challenge fee per evaluation row is interpreted as:
  challenge_fee = Fee + Activation Fee

Dates:
  Prefer Date Purchased, then Date, then Date Started.

Highlights:
  Any challenge_fee > --highlight (default: 200) is flagged.

Examples:
  python scripts/print_client_challenge_fees.py --client "Thak Mano"
  python scripts/print_client_challenge_fees.py --client "Thak Mano" --include-kyc
  python scripts/print_client_challenge_fees.py --client "Thak Mano" --highlight 200
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
    from dashboard.database import get_connection, get_all_kyc_accounts  # type: ignore
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


def _write_html_report(
    path: str,
    title: str,
    subtitle: str,
    table_html: str,
    totals_html: str,
    highlight_label: str,
) -> str:
    css = """
    :root { --bg:#0b1020; --card:#111a33; --text:#e8ecff; --muted:#aeb8e6; --grid:#243055; --accent:#7aa2ff;
            --bad:#ff5c7a; --badbg: rgba(255,92,122,.10); }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1280px; margin: 28px auto; padding: 0 18px 40px; }
    .head { display:flex; gap:16px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; }
    h1 { margin:0; font-size: 22px; letter-spacing: .2px; }
    .sub { margin:6px 0 0; color:var(--muted); font-size: 13px; }
    .card { background: var(--card); border:1px solid var(--grid); border-radius: 14px; padding: 14px 16px; }
    .cards { display:grid; grid-template-columns: repeat(4, minmax(210px, 1fr)); gap: 12px; margin-top: 14px; }
    .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .v { font-size: 20px; margin-top: 6px; }
    .tablewrap { margin-top: 14px; overflow:auto; border-radius: 14px; border:1px solid var(--grid); }
    table { width:100%; border-collapse: collapse; background: var(--card); }
    th, td { padding: 10px 10px; border-bottom: 1px solid var(--grid); font-size: 13px; white-space: nowrap; }
    th { position: sticky; top:0; background: #0f1834; color: var(--muted); text-align:left; font-weight: 600; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    tr.flag td { background: var(--badbg); }
    .flag-pill { display:inline-block; padding: 3px 8px; border-radius: 999px; background: rgba(255,92,122,.12);
                 border:1px solid rgba(255,92,122,.35); color: var(--text); font-size: 12px; }
    .badge { display:inline-block; padding: 3px 8px; border-radius: 999px; background: rgba(122,162,255,.12); border:1px solid rgba(122,162,255,.35); color: var(--text); font-size: 12px; }
    .hint { margin-top: 10px; color: var(--muted); font-size: 12px; }
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
        <div class="hint">Highlighted rows are {html.escape(highlight_label)}.</div>
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


@dataclass(frozen=True)
class FeeRow:
    client_id: str
    client_name: str
    prop_firm: str
    account: str
    date_raw: str
    date_obj: Optional[datetime]
    fee: float
    activation_fee: float
    challenge_fee: float


def _iter_fees_for_evaluations(
    client_id: str,
    client_name: str,
    evaluations: Iterable[Dict[str, Any]],
) -> Iterable[FeeRow]:
    for ev in evaluations:
        if not isinstance(ev, dict):
            continue

        firm = normalize_prop_firm(ev.get("Prop Firm"))
        account = str(ev.get("Account #") or ev.get("Account #.1") or ev.get("Account") or "-").strip()

        fee = parse_currency(ev.get("Fee"))
        activation_fee = parse_currency(ev.get("Activation Fee"))
        challenge_fee = round(float(fee + activation_fee), 2)
        if challenge_fee <= 0:
            continue

        # Choose best available fee date
        date_raw = str(
            ev.get("Date Purchased") or ev.get("Date") or ev.get("Date Started") or ""
        ).strip()
        date_obj = _parse_date_maybe(date_raw)

        yield FeeRow(
            client_id=client_id,
            client_name=client_name,
            prop_firm=firm or "Unknown",
            account=account or "-",
            date_raw=date_raw or "-",
            date_obj=date_obj,
            fee=float(fee),
            activation_fee=float(activation_fee),
            challenge_fee=challenge_fee,
        )


def _fetch_clients_rows() -> List[Dict[str, Any]]:
    with get_connection() as conn:  # type: ignore[misc]
        cur = conn.cursor()
        cur.execute("SELECT client_id, identity, evaluations FROM clients_data")
        return cur.fetchall() or []


def _load_matching_client_rows(target_client: str) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
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
        help="If client is KYC-linked, include challenge fees for linked accounts too.",
    )
    ap.add_argument(
        "--highlight",
        type=float,
        default=200.0,
        help="Highlight challenge fees strictly greater than this amount (default: 200).",
    )
    ap.add_argument(
        "--html",
        nargs="?",
        const="",
        default=None,
        help="Write an HTML report (optional path; default: reports/<client>-challenge-fees.html).",
    )
    args = ap.parse_args()

    client_rows = _load_matching_client_rows(args.client)
    if not client_rows:
        print(f"No client match found for: {args.client!r}")
        return 2

    client_ids = [cid for (cid, _name, _evals) in client_rows]
    if args.include_kyc:
        expanded: List[str] = []
        for cid, name, _evals in client_rows:
            base = name or cid
            try:
                expanded.extend(get_all_kyc_accounts(base))
            except Exception:
                expanded.append(base)

        seen = set()
        expanded_unique: List[str] = []
        for x in expanded:
            nx = str(x).strip()
            if nx and nx not in seen:
                seen.add(nx)
                expanded_unique.append(nx)

        reloaded: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        for name in expanded_unique:
            reloaded.extend(_load_matching_client_rows(name))

        dedup: Dict[str, Tuple[str, str, List[Dict[str, Any]]]] = {}
        for cid, name, evals in reloaded:
            dedup[cid] = (cid, name, evals)
        client_rows = list(dedup.values())
        client_ids = [cid for (cid, _name, _evals) in client_rows]

    fees: List[FeeRow] = []
    for cid, display_name, evals in client_rows:
        fees.extend(list(_iter_fees_for_evaluations(cid, display_name, evals)))

    # Sort: date desc first; unknown dates last
    fees.sort(
        key=lambda r: (
            0 if r.date_obj else 1,
            r.date_obj or datetime.min,
        ),
        reverse=True,
    )

    header = f"Challenge fees for: {args.client}  (matched client_id(s): {', '.join(client_ids)})"
    subtitle = f"Matched client_id(s): {', '.join(client_ids)}"
    print(header)
    print("-" * max(60, len(header)))

    if not fees:
        print("No challenge fees found (Fee+Activation Fee <= 0 on all evaluation rows).")
        return 0

    total = 0.0
    flagged_total = 0.0
    flagged_count = 0

    print(f"{'Date':<12} {'Ch.Fee':>12}  {'Fee':>10} {'Act':>10}  {'Firm':<22}  {'Account':<12}  {'Client':<20}  Flag")
    print("-" * 120)
    for r in fees:
        total += r.challenge_fee
        is_flagged = r.challenge_fee > float(args.highlight)
        if is_flagged:
            flagged_total += r.challenge_fee
            flagged_count += 1

        date_out = (r.date_obj.strftime("%Y-%m-%d") if r.date_obj else r.date_raw)[:12]
        flag = "!! >" + str(int(args.highlight)) if is_flagged else ""
        print(
            f"{date_out:<12} ${r.challenge_fee:>10,.2f}  ${r.fee:>8,.2f} ${r.activation_fee:>8,.2f}  "
            f"{r.prop_firm[:22]:<22}  {r.account[:12]:<12}  {r.client_name[:20]:<20}  {flag}"
        )

    print("-" * 120)
    print(f"Total challenge fees: ${total:,.2f}   (count: {len(fees)})")
    print(f"Flagged > ${args.highlight:,.2f}: ${flagged_total:,.2f}   (count: {flagged_count})")

    if args.html is not None:
        out = args.html
        if out == "":
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(args.client).strip()).strip("-") or "client"
            reports_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "reports")
            os.makedirs(reports_dir, exist_ok=True)
            out = os.path.join(reports_dir, f"{safe}-challenge-fees.html")

        rows_html = []
        for r in fees:
            date_out = (r.date_obj.strftime("%Y-%m-%d") if r.date_obj else r.date_raw)[:32]
            is_flagged = r.challenge_fee > float(args.highlight)
            tr_cls = " class='flag'" if is_flagged else ""
            flag_html = "<span class='flag-pill'>HIGH</span>" if is_flagged else ""
            rows_html.append(
                f"<tr{tr_cls}>"
                f"<td>{html.escape(date_out or '-')}</td>"
                f"<td class='num'>{html.escape(_money(r.challenge_fee))}</td>"
                f"<td class='num'>{html.escape(_money(r.fee))}</td>"
                f"<td class='num'>{html.escape(_money(r.activation_fee))}</td>"
                f"<td>{html.escape(r.prop_firm)}</td>"
                f"<td>{html.escape(r.account)}</td>"
                f"<td>{html.escape(r.client_name)}</td>"
                f"<td>{flag_html}</td>"
                "</tr>"
            )

        table_html = (
            "<table>"
            "<thead><tr>"
            "<th>Date</th>"
            "<th class='num'>Challenge Fee</th>"
            "<th class='num'>Fee</th>"
            "<th class='num'>Activation</th>"
            "<th>Firm</th>"
            "<th>Account</th>"
            "<th>Client</th>"
            "<th>Flag</th>"
            "</tr></thead>"
            "<tbody>"
            + "".join(rows_html)
            + "</tbody></table>"
        )

        totals_html = (
            f"<div class='card'><div class='k'>Total challenge fees</div><div class='v'>{html.escape(_money(total))}</div></div>"
            f"<div class='card'><div class='k'>Fee rows</div><div class='v'>{len(fees):,}</div></div>"
            f"<div class='card'><div class='k'>Flagged &gt; {html.escape(_money(float(args.highlight)))}</div><div class='v'>{flagged_count:,}</div><div class='sub'>{html.escape(_money(flagged_total))} total</div></div>"
            f"<div class='card'><div class='k'>Report</div><div class='v'>Challenge Fees</div><div class='sub'>{html.escape(args.client)}</div></div>"
        )

        abs_out = _write_html_report(
            out,
            f"Challenge Fees — {args.client}",
            subtitle,
            table_html,
            totals_html,
            highlight_label=f"challenge fee > {_money(float(args.highlight))}",
        )
        print(f"\nHTML written: {abs_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

