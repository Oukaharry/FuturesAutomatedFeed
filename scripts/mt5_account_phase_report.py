#!/usr/bin/env python3
"""
Connect to MetaTrader 5, filter deal history by Tradovate account suffix (last 5 digits
in order comments), categorize by phase (CH / FD / FA), and print a self-contained HTML report.

Comments look like: FNFT...54738_FA, AFAD...53074_FD1, MFFU...97120_CH1

Usage:
    1. Edit MT5_LOGIN, MT5_PASSWORD, ACCOUNT_SUFFIX below.
    2. Run: python scripts/mt5_account_phase_report.py

    HTML is written with auto-incrementing names: report.html, report1.html, report2.html, …

Requires MetaTrader 5 terminal installed and the MetaTrader5 Python package.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 package is not installed. Run: pip install MetaTrader5", file=sys.stderr)
    sys.exit(1)

from trader_companion.mt5_comment_parser import MT5CommentParser, Phase


# =============================================================================
# EDIT THESE — then run:  python scripts/mt5_account_phase_report.py
# =============================================================================
MT5_LOGIN = 3000951                    # e.g. 12345678
MT5_PASSWORD = "Futures2026$$"                # your MT5 password
ACCOUNT_SUFFIX = "6481"              # last 4–5 digits (5 tried first, then last 4 as fallback)
MT5_SERVER = "PlexyTrade-Server01"                  # optional broker server; leave "" to try without, then retry
# Default Windows install (override only if MT5 is elsewhere)
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
OUTPUT_FILE = "report.html"      # base name; each run creates report.html, report1.html, report2.html, …
# =============================================================================

# Standard Windows MT5 locations (checked in order if the path above is missing)
_WINDOWS_MT5_TERMINAL_CANDIDATES = (
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe",
)


def resolve_mt5_terminal_path(override: str = "") -> str:
    """Return path to terminal64.exe (folder or full .exe accepted for override)."""
    if override and override.strip():
        p = override.strip().strip('"')
        if os.path.isdir(p):
            p = os.path.join(p, "terminal64.exe")
        if os.path.isfile(p):
            return p
    for candidate in _WINDOWS_MT5_TERMINAL_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    if override and override.strip():
        p = override.strip().strip('"')
        if os.path.isdir(p):
            p = os.path.join(p, "terminal64.exe")
        return p
    return _WINDOWS_MT5_TERMINAL_CANDIDATES[0]


DEAL_TYPE_NAMES = {
    0: "BUY",
    1: "SELL",
    2: "BALANCE",
    3: "CREDIT",
    4: "CHARGE",
    5: "CORRECTION",
    6: "BONUS",
}
ENTRY_NAMES = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
BALANCE_TYPES = frozenset({"BALANCE", "CREDIT", "CHARGE", "CORRECTION", "BONUS", "2", "3", "4", "5", "6"})


def _deal_type_name(deal_type: int) -> str:
    return DEAL_TYPE_NAMES.get(deal_type, str(deal_type))


def _entry_name(entry: int) -> str:
    return ENTRY_NAMES.get(entry, str(entry))


def _net_profit(deal: Dict[str, Any]) -> float:
    return (
        float(deal.get("profit") or 0)
        + float(deal.get("commission") or 0)
        + float(deal.get("swap") or 0)
        + float(deal.get("fee") or 0)
    )


def _extract_account_token(comment: str) -> Optional[str]:
    """Account id immediately before _CH/_FD/_DD/_FA (handles V2-...2318_FA)."""
    if not comment:
        return None
    c = comment.strip()
    m = re.search(r"\.\.\.\s*([A-Za-z0-9]+)_(CH|FD|DD|FA)(\d*)", c, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r"([A-Za-z0-9]+)_(CH|FD|DD|FA)(\d*)", c, re.IGNORECASE)
    return m.group(1).upper() if m else None


def build_suffix_candidates(user_input: str) -> List[str]:
    """
    Build suffix list to try: 5 digits first, then last 4 (V2-...2318 style comments).
    Input may be 4 or 5+ digits (uses trailing digits).
    """
    s = user_input.strip()
    if not s.isdigit() or len(s) < 4:
        return []
    out: List[str] = []
    if len(s) >= 5:
        out.append(s[-5:])
        four = s[-4:]
        if four not in out:
            out.append(four)
    else:
        out.append(s)
    return out


def _token_matches_suffix(token: str, suffix: str) -> bool:
    """Match account token to 4- or 5-digit suffix (FNFT...N5786, V2-...2318)."""
    if not token or not suffix:
        return False
    token_u = token.upper()
    suf = suffix.strip()
    if not suf.isdigit() or len(suf) not in (4, 5):
        return False
    if token_u.endswith(suf):
        return True
    # Trailing digits in alphanumeric token (e.g. N5786 + suffix 5786)
    m = re.search(r"(\d+)$", token_u)
    if m and m.group(1).endswith(suf):
        return True
    return False


def comment_matches_suffix(comment: str, suffix: str) -> bool:
    """True if comment belongs to the account identified by a 4- or 5-digit suffix."""
    if not comment or not suffix:
        return False
    suffix = suffix.strip()
    if not suffix.isdigit() or len(suffix) not in (4, 5):
        return False

    token = _extract_account_token(comment)
    if token and _token_matches_suffix(token, suffix):
        return True

    # Truncated comment: PREFIX...3584_FA or V2-...2318_CH1
    return bool(
        re.search(
            rf"(?:\.{{2,}}|[^A-Za-z0-9]){re.escape(suffix)}_(?:CH|FD|DD|FA)\d*\b",
            comment,
            re.IGNORECASE,
        )
    )


def comment_matches_any_suffix(comment: str, suffixes: List[str]) -> bool:
    return any(comment_matches_suffix(comment, s) for s in suffixes)


def _position_comment(deal_list: List[Dict[str, Any]]) -> str:
    """Best comment for a position (entry deal often has it; exit may be blank)."""
    for d in deal_list:
        c = (d.get("comment") or "").strip()
        if re.search(r"_(CH|FD|DD|FA)\b", c, re.IGNORECASE):
            return c
    for d in deal_list:
        c = (d.get("comment") or "").strip()
        if c:
            return c
    return ""


def count_comment_matches(deals: List[Dict[str, Any]], suffix: str) -> int:
    return sum(1 for d in deals if comment_matches_suffix(d.get("comment", ""), suffix))


def resolve_active_suffix(
    deals: List[Dict[str, Any]], candidates: List[str]
) -> Tuple[str, List[str]]:
    """Pick first candidate with matches; if none, return last candidate for empty report."""
    for cand in candidates:
        if count_comment_matches(deals, cand) > 0:
            return cand, [cand]
    return (candidates[-1] if candidates else ""), candidates


def deal_to_dict(deal) -> Dict[str, Any]:
    t = deal.time
    return {
        "ticket": deal.ticket,
        "order": deal.order,
        "position_id": deal.position_id,
        "symbol": deal.symbol,
        "type": _deal_type_name(deal.type),
        "type_raw": deal.type,
        "entry": _entry_name(deal.entry),
        "entry_raw": deal.entry,
        "volume": deal.volume,
        "price": deal.price,
        "profit": deal.profit,
        "commission": deal.commission,
        "swap": deal.swap,
        "fee": deal.fee,
        "time": datetime.fromtimestamp(t),
        "time_ts": t,
        "magic": deal.magic,
        "comment": deal.comment or "",
    }


def fetch_all_deals() -> List[Dict[str, Any]]:
    from_ts = 0.0
    to_ts = time.time() + 86400
    raw = mt5.history_deals_get(from_ts, to_ts)
    if raw is None:
        return []
    return [deal_to_dict(d) for d in raw]


def _is_balance_deal(d: Dict[str, Any]) -> bool:
    t = str(d.get("type", "")).upper()
    if t in BALANCE_TYPES:
        return True
    comment = (d.get("comment") or "").lower()
    return "internal transfer" in comment


def group_positions(deals: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Build one row per closed position (IN+OUT aggregated) and keep orphan deals separate.
    """
    by_pos: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    orphans: List[Dict[str, Any]] = []

    for d in deals:
        if _is_balance_deal(d):
            continue
        pid = int(d.get("position_id") or 0)
        if pid > 0:
            by_pos[pid].append(d)
        else:
            orphans.append(d)

    rows: List[Dict[str, Any]] = []
    parser = MT5CommentParser()

    for pid, deal_list in by_pos.items():
        deal_list.sort(key=lambda x: x["time_ts"])
        entry_deal = None
        exit_time_ts = 0
        has_exit = False
        totals = {"profit": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0}

        for d in deal_list:
            entry_raw = d.get("entry_raw")
            entry_str = str(d.get("entry", "")).upper()
            is_in = entry_raw == 0 or entry_str == "IN"
            is_out = entry_raw in (1, 2, 3) or entry_str in ("OUT", "INOUT", "OUT_BY")

            if is_in and entry_deal is None:
                entry_deal = d
            if is_out:
                has_exit = True
            if d["time_ts"] > exit_time_ts:
                exit_time_ts = d["time_ts"]

            totals["profit"] += float(d.get("profit") or 0)
            totals["commission"] += float(d.get("commission") or 0)
            totals["swap"] += float(d.get("swap") or 0)
            totals["fee"] += float(d.get("fee") or 0)

        if not entry_deal:
            for d in deal_list:
                c = d.get("comment") or ""
                if re.search(r"_(CH|FD|DD|FA)", c, re.I):
                    entry_deal = d
                    break
        if not entry_deal:
            entry_deal = deal_list[0]

        comment = _position_comment(deal_list)
        parsed = parser.parse(comment)
        close_time = datetime.fromtimestamp(exit_time_ts) if exit_time_ts else entry_deal["time"]

        rows.append(
            {
                "position_id": pid,
                "ticket": entry_deal.get("ticket"),
                "symbol": entry_deal.get("symbol") or deal_list[-1].get("symbol"),
                "comment": comment,
                "parsed": parsed,
                "open_time": entry_deal["time"],
                "close_time": close_time,
                "close_time_ts": exit_time_ts or entry_deal["time_ts"],
                "volume": entry_deal.get("volume"),
                "profit": totals["profit"],
                "commission": totals["commission"],
                "swap": totals["swap"],
                "fee": totals["fee"],
                "net_profit": round(
                    totals["profit"] + totals["commission"] + totals["swap"] + totals["fee"], 2
                ),
                "deal_count": len(deal_list),
                "has_exit": has_exit,
                "deals": deal_list,
            }
        )

    return rows, orphans


def assign_farming_days(fa_rows: List[Dict[str, Any]]) -> None:
    """Set farming_day on each FA row from unique close dates (earliest = Day 1)."""
    day_map: Dict[str, datetime] = {}

    for row in fa_rows:
        parsed = row["parsed"]
        if parsed.farming_date:
            day_key = parsed.farming_date.date().isoformat()
        else:
            day_key = row["close_time"].date().isoformat()
        row["_fa_date_key"] = day_key
        if day_key not in day_map:
            day_map[day_key] = datetime.strptime(day_key, "%Y-%m-%d")

    ordered_days = sorted(day_map.items(), key=lambda x: x[1])
    day_number = {k: i + 1 for i, (k, _) in enumerate(ordered_days)}

    for row in fa_rows:
        row["farming_day"] = day_number[row["_fa_date_key"]]
        row["farming_day_label"] = f"Farming Day {day_number[row['_fa_date_key']]}"
        row["farming_date_display"] = row["_fa_date_key"]


def categorize_rows(rows: List[Dict[str, Any]], suffixes: List[str]) -> Dict[str, Any]:
    parser = MT5CommentParser()
    matched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for row in rows:
        comment = row.get("comment") or ""
        if not comment_matches_any_suffix(comment, suffixes):
            skipped.append(row)
            continue
        parsed = row.get("parsed") or parser.parse(comment)
        row["parsed"] = parsed
        if not parsed.is_valid:
            skipped.append(row)
            continue
        matched.append(row)

    challenge: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    funded: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    double_dip: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    farming: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []

    for row in matched:
        p = row["parsed"]
        if p.phase == Phase.CHALLENGE and p.trade_number is not None:
            challenge[p.trade_number].append(row)
        elif p.phase == Phase.FUNDED and p.trade_number is not None:
            funded[p.trade_number].append(row)
        elif p.phase == Phase.DOUBLE_DIP and p.trade_number is not None:
            double_dip[p.trade_number].append(row)
        elif p.phase == Phase.FARMING:
            farming.append(row)
        else:
            other.append(row)

    assign_farming_days(farming)

    def sort_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda r: r["close_time_ts"])

    for bucket in (challenge, funded, double_dip):
        for k in bucket:
            bucket[k] = sort_rows(bucket[k])
    farming = sorted(farming, key=lambda r: (r.get("farming_day", 0), r["close_time_ts"]))

    return {
        "challenge": dict(sorted(challenge.items())),
        "funded": dict(sorted(funded.items())),
        "double_dip": dict(sorted(double_dip.items())),
        "farming": farming,
        "farming_by_day": _group_farming_by_day(farming),
        "other": sort_rows(other),
        "skipped": skipped,
        "matched": matched,
    }


def _group_farming_by_day(farming: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    by_day: Dict[int, Dict[str, Any]] = {}
    for row in farming:
        day = row.get("farming_day", 0)
        if day not in by_day:
            by_day[day] = {
                "label": row.get("farming_day_label", f"Farming Day {day}"),
                "date": row.get("farming_date_display", ""),
                "rows": [],
                "net_profit": 0.0,
            }
        by_day[day]["rows"].append(row)
        by_day[day]["net_profit"] += row["net_profit"]
    for d in by_day.values():
        d["net_profit"] = round(d["net_profit"], 2)
    return dict(sorted(by_day.items()))


def _fmt_money(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.2f}"


def _profit_class(v: float) -> str:
    if v > 0:
        return "profit-pos"
    if v < 0:
        return "profit-neg"
    return "profit-zero"


def _flatten_categorized_rows(categories: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One list of rows with phase labels for the single-table report."""
    flat: List[Dict[str, Any]] = []

    def add(rows: List[Dict[str, Any]], phase: str, code: str, sort: Tuple) -> None:
        for r in rows:
            flat.append({**r, "phase_group": phase, "phase_code": code, "_sort": sort})

    for num, rows in categories["challenge"].items():
        for r in rows:
            add([r], "Challenge", f"CH{num}", (0, num, r["close_time_ts"]))
    for num, rows in categories["funded"].items():
        for r in rows:
            add([r], "Funded", f"FD{num}", (1, num, r["close_time_ts"]))
    for num, rows in categories["double_dip"].items():
        for r in rows:
            add([r], "Double Dip", f"DD{num}", (2, num, r["close_time_ts"]))
    for r in categories["farming"]:
        day = r.get("farming_day", 0)
        add([r], "Farming", f"FA D{day}", (3, day, r["close_time_ts"]))
    for r in categories["other"]:
        parsed = r.get("parsed")
        code = "?"
        if parsed and parsed.phase_code:
            n = parsed.trade_number
            code = f"{parsed.phase_code}{n}" if n else parsed.phase_code
        add([r], "Other", code, (4, 0, r["close_time_ts"]))

    flat.sort(key=lambda x: x["_sort"])
    return flat


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%m/%d %H:%M")


def _render_flat_table(rows: List[Dict[str, Any]], total_net: float) -> str:
    if not rows:
        return "<p class='empty'>No matching trades.</p>"

    headers = ["Phase", "Pos", "Symbol", "Open", "Close", "Vol", "Net P/L", "Comment"]
    out = ['<div class="table-wrap"><table class="main"><thead><tr>']
    for h in headers:
        out.append(f"<th>{html.escape(h)}</th>")
    out.append("</tr></thead><tbody>")

    for row in rows:
        net = row["net_profit"]
        out.append("<tr>")
        out.append(
            f'<td class="phase"><span class="pg">{html.escape(row["phase_group"])}</span> '
            f'<strong>{html.escape(row["phase_code"])}</strong></td>'
        )
        out.append(f'<td class="num">{row.get("position_id", "")}</td>')
        out.append(f"<td>{html.escape(str(row.get('symbol', '')))}</td>")
        out.append(f'<td class="dt">{html.escape(_fmt_dt(row["open_time"]))}</td>')
        out.append(f'<td class="dt">{html.escape(_fmt_dt(row["close_time"]))}</td>')
        out.append(f'<td class="num">{row.get("volume", "")}</td>')
        out.append(f'<td class="num {_profit_class(net)}">{_fmt_money(net)}</td>')
        out.append(f'<td class="comment">{html.escape(row.get("comment", ""))}</td>')
        out.append("</tr>")

    out.append("</tbody><tfoot><tr>")
    out.append(f'<td colspan="6"><strong>Total ({len(rows)} positions)</strong></td>')
    out.append(f'<td class="num {_profit_class(total_net)}"><strong>{_fmt_money(total_net)}</strong></td>')
    out.append("<td></td></tr></tfoot></table></div>")
    return "\n".join(out)


def render_html(
    mt5_login: int,
    account_suffix: str,
    connection_msg: str,
    categories: Dict[str, Any],
    total_deals_scanned: int,
) -> str:
    matched = categories["matched"]
    flat_rows = _flatten_categorized_rows(categories)
    total_net = round(sum(r["net_profit"] for r in matched), 2)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ch_n = sum(len(v) for v in categories["challenge"].values())
    fd_n = sum(len(v) for v in categories["funded"].values())
    fa_n = len(categories["farming"])
    summary_bits = [
        f"CH {ch_n} · {_fmt_money(_phase_net(categories['challenge']))}",
        f"FD {fd_n} · {_fmt_money(_phase_net(categories['funded']))}",
        f"FA {fa_n} · {_fmt_money(round(sum(r['net_profit'] for r in categories['farming']), 2))}",
    ]
    if categories["double_dip"]:
        dd_n = sum(len(v) for v in categories["double_dip"].values())
        summary_bits.insert(2, f"DD {dd_n} · {_fmt_money(_phase_net(categories['double_dip']))}")

    main_table = _render_flat_table(flat_rows, total_net)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>MT5 Phase Report — …{html.escape(account_suffix)}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --pos: #22c55e;
      --neg: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 1rem 1.25rem;
      line-height: 1.35;
      font-size: 13px;
    }}
    h1 {{ margin: 0 0 0.35rem; font-size: 1.25rem; }}
    .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 0.75rem; }}
    .totals {{ font-size: 0.85rem; margin-bottom: 0.5rem; }}
    .totals span {{ margin-right: 1.25rem; white-space: nowrap; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
    table.main {{
      width: 100%;
      border-collapse: collapse;
      white-space: nowrap;
    }}
    th, td {{
      padding: 0.35rem 0.5rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: #1a2332;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    tbody tr:hover td {{ background: rgba(59, 130, 246, 0.08); }}
    tfoot td {{
      border-top: 2px solid var(--border);
      background: #1a2332;
    }}
    td.phase .pg {{ color: var(--muted); font-size: 0.7rem; display: block; line-height: 1.1; }}
    td.phase strong {{ font-size: 0.85rem; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    th:nth-child(n+3), td:nth-child(n+3):not(.phase):not(.comment) {{ text-align: right; }}
    td.dt {{ text-align: left !important; color: var(--muted); font-size: 0.8rem; }}
    td.comment {{
      font-family: Consolas, monospace;
      font-size: 0.75rem;
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      text-align: left !important;
    }}
    .profit-pos {{ color: var(--pos); font-weight: 600; }}
    .profit-neg {{ color: var(--neg); font-weight: 600; }}
    .profit-zero {{ color: var(--muted); }}
    .empty {{ color: var(--muted); }}
  </style>
</head>
<body>
  <h1>MT5 Phase Report · …{html.escape(account_suffix)}</h1>
  <p class="meta">
    Login {mt5_login} · {html.escape(connection_msg)} · {generated} ·
    {len(matched)} positions from {total_deals_scanned} deals
  </p>
  <p class="totals">{"".join(f'<span>{html.escape(s)}</span>' for s in summary_bits)}</p>
  {main_table}
</body>
</html>"""


def _phase_net(phase_dict: Dict[int, List[Dict[str, Any]]]) -> float:
    return round(sum(r["net_profit"] for rows in phase_dict.values() for r in rows), 2)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def next_numbered_output_path(output_file: str) -> str:
    """
    Pick the next unused report path so runs do not overwrite prior HTML.

    report.html → report1.html → report2.html → …
    """
    path = output_file
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)

    directory, basename = os.path.dirname(path), os.path.basename(path)
    stem, ext = os.path.splitext(basename)
    if not ext:
        ext = ".html"
        stem = basename or "report"

    first = os.path.join(directory, f"{stem}{ext}")
    if not os.path.exists(first):
        return first

    n = 1
    while True:
        candidate = os.path.join(directory, f"{stem}{n}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _write_report(doc: str, output_file: str) -> None:
    """
    Write HTML to OUTPUT_FILE, or to stdout if the shell redirected it (e.g. > report.html).

    Do not use shell redirect when OUTPUT_FILE is set — that locks the same file and causes
    PermissionError. Run:  python scripts/mt5_account_phase_report.py
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not sys.stdout.isatty():
        _log(
            "Stdout is redirected (e.g. > report.html) — HTML written to stdout only. "
            "Next time run without '>' ; the script writes OUTPUT_FILE itself."
        )
        print(doc)
        return

    path = next_numbered_output_path(output_file)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
    except PermissionError:
        alt = os.path.join(
            os.path.dirname(path),
            f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
        )
        _log(f"Could not write {path} (file open or locked?). Writing to {alt}")
        with open(alt, "w", encoding="utf-8") as f:
            f.write(doc)
        path = alt

    _log(f"Report written to: {path}")
    _log("Open that file in your browser.")


def main() -> int:
    ap = argparse.ArgumentParser(description="MT5 deal history by account comment suffix → HTML report")
    ap.add_argument("--output", "-o", help="Override OUTPUT_FILE from config")
    ap.add_argument("--server", help="Override MT5_SERVER from config")
    ap.add_argument("--terminal", help="Override MT5_TERMINAL_PATH from config")
    ap.add_argument("--login", type=int, help="Override MT5_LOGIN from config")
    ap.add_argument("--password", help="Override MT5_PASSWORD from config")
    ap.add_argument("--suffix", help="Override ACCOUNT_SUFFIX from config")
    args = ap.parse_args()

    login = args.login if args.login is not None else MT5_LOGIN
    password = args.password if args.password is not None else MT5_PASSWORD
    suffix = (args.suffix or ACCOUNT_SUFFIX).strip()
    server = (args.server or MT5_SERVER or "").strip()
    terminal_override = (args.terminal or MT5_TERMINAL_PATH or "").strip()
    terminal_exe = resolve_mt5_terminal_path(terminal_override)
    output_file = args.output if args.output is not None else OUTPUT_FILE

    if not login or not password or not suffix:
        _log(
            "Set MT5_LOGIN, MT5_PASSWORD, and ACCOUNT_SUFFIX at the top of "
            "scripts/mt5_account_phase_report.py (or pass --login, --password, --suffix)."
        )
        return 1
    suffix_candidates = build_suffix_candidates(suffix)
    if not suffix_candidates:
        _log("Account suffix must be 4 or 5 digits (numeric).")
        return 1

    try:
        login = int(login)
    except (TypeError, ValueError):
        _log("MT5 login must be a number.")
        return 1

    _log("MT5 Account Phase Report")
    _log("=" * 40)
    _log(f"MT5 terminal: {terminal_exe}")

    if not os.path.isfile(terminal_exe):
        _log(f"Warning: terminal not found at {terminal_exe}")

    if not mt5.initialize(path=terminal_exe):
        _log(f"MT5 initialize failed: {mt5.last_error()}")
        return 1

    ok = mt5.login(login, password=password, server=server) if server else mt5.login(login, password=password)

    if not ok:
        _log(f"MT5 login failed: {mt5.last_error()}")
        if not server:
            _log("Tip: set MT5_SERVER in the config block (broker server name from MT5).")
        mt5.shutdown()
        return 1

    info = mt5.account_info()
    conn_msg = f"Connected to #{info.login} on {info.server}" if info else f"Connected as {login}"

    try:
        deals = fetch_all_deals()
        active_suffix, match_suffixes = resolve_active_suffix(deals, suffix_candidates)
        if len(suffix_candidates) > 1 and active_suffix != suffix_candidates[0]:
            _log(
                f"No comments matched …{suffix_candidates[0]}; "
                f"using 4-digit fallback …{active_suffix}"
            )
        elif active_suffix:
            _log(f"Matching account suffix …{active_suffix}")

        position_rows, orphans = group_positions(deals)

        # Also include orphan deals that match directly
        for d in orphans:
            if _is_balance_deal(d):
                continue
            if not comment_matches_any_suffix(d.get("comment", ""), match_suffixes):
                continue
            parser = MT5CommentParser()
            parsed = parser.parse(d.get("comment", ""))
            position_rows.append(
                {
                    "position_id": d.get("ticket"),
                    "ticket": d.get("ticket"),
                    "symbol": d.get("symbol"),
                    "comment": d.get("comment"),
                    "parsed": parsed,
                    "open_time": d["time"],
                    "close_time": d["time"],
                    "close_time_ts": d["time_ts"],
                    "volume": d.get("volume"),
                    "profit": d.get("profit"),
                    "commission": d.get("commission"),
                    "swap": d.get("swap"),
                    "fee": d.get("fee"),
                    "net_profit": round(_net_profit(d), 2),
                    "deal_count": 1,
                    "has_exit": True,
                    "deals": [d],
                }
            )

        categories = categorize_rows(position_rows, match_suffixes)
        doc = render_html(login, active_suffix, conn_msg, categories, len(deals))

        if output_file:
            _write_report(doc, output_file)
        else:
            if hasattr(sys.stdout, "reconfigure"):
                try:
                    sys.stdout.reconfigure(encoding="utf-8")
                except Exception:
                    pass
            print(doc)
    finally:
        mt5.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
