"""
scripts/_compare_mt5_vs_db.py
------------------------------
Compare trades in an MT5 HTML report vs the database evaluations for a client.

Usage:
    python scripts/_compare_mt5_vs_db.py "Rob Madsen"
    python scripts/_compare_mt5_vs_db.py "Fabian Omondi"

The script:
  1. Finds mt5_reports/<FirstName_LastName>.html
  2. Parses all trades, groups net P&L by comment (account ref)
  3. Loads the client's evaluations from PostgreSQL
  4. For each evaluation row, finds ALL numeric fields and checks if the
     comment-grouped total from the HTML matches any of them
  5. Writes a colour-coded HTML report and opens it in the browser
"""

import json
import logging
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer


# ---------------------------------------------------------------------------
# Config / DB connection
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8", errors="replace") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    sys.exit("ERROR: Set DATABASE_URL to your PostgreSQL connection string in .env")

# ---------------------------------------------------------------------------
# Logging — discrepancies.log (project root) + console mirror
# ---------------------------------------------------------------------------
_LOG_FILE = os.path.join(ROOT, "discrepancies.log")
_log_fmt  = logging.Formatter(
    "[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_fh = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
_fh.setFormatter(_log_fmt)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_log_fmt)
log = logging.getLogger("discrepancies")
log.setLevel(logging.DEBUG)
log.addHandler(_fh)
log.addHandler(_ch)
log.propagate = False

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")

# Pull in the trader companion comment parser for account signature matching
sys.path.insert(0, os.path.join(ROOT, "trader_companion"))
sys.path.insert(0, ROOT)  # for utils.data_processor
try:
    from mt5_comment_parser import get_account_signature, MT5CommentParser
    _PARSER = MT5CommentParser()
except ImportError:
    # Fallback: inline the signature function if trader_companion isn't importable
    def get_account_signature(account: str) -> str:
        if not account:
            return ""
        account = account.strip()
        if "..." in account:
            parts = account.split("...")
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]
            return (prefix + suffix).lower()
        if len(account) <= 8:
            return account.lower()
        return (account[:4] + account[-4:]).lower()
    _PARSER = None

try:
    from utils.data_processor import calculate_statistics
except ImportError:
    calculate_statistics = None
    log.warning("Could not import calculate_statistics from utils.data_processor")


# ---------------------------------------------------------------------------
# Currency parser (handles MT5 format: '49 700.00', '- 131.45', '−50.00')
# ---------------------------------------------------------------------------
def parse_currency(val):
    if not val or not str(val).strip():
        return 0.0
    s = str(val).replace("\xa0", " ").strip()
    s = re.sub(r"[−–]", "-", s)
    s = re.sub(r"-\s+", "-", s)
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_num(val):
    """Return float if a DB field value looks numeric, else None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.replace(",", "").replace("$", "").replace(" ", "").strip()
        # Accounting negative: (163.52) → -163.52
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Parse MT5 HTML report
# ---------------------------------------------------------------------------
def parse_mt5_html(html_path):
    """
    Returns list of dicts, one per closed trade:
      { open_time, position_id, symbol, type, commission, swap, profit,
        net, account_ref }
    """
    encodings = ["utf-16", "utf-8", "cp1252"]
    soup = None
    for enc in encodings:
        try:
            with open(html_path, encoding=enc, errors="replace") as fh:
                soup = BeautifulSoup(fh.read(), "html.parser")
            break
        except Exception:
            continue
    if soup is None:
        sys.exit(f"ERROR: Could not read {html_path}")

    rows = soup.find_all("tr")

    in_positions = False
    header_row_done = False
    headers = []
    trades = []

    for row in rows:
        tds = row.find_all(["td", "th"])
        if not tds:
            continue

        # Detect section headers
        first_text = tds[0].get_text(strip=True)
        if first_text in ("Positions", "Orders", "Deals", "Balance"):
            in_positions = first_text in ("Positions",)
            header_row_done = False
            headers = []
            continue

        if not in_positions:
            continue

        # Capture column headers (the bold row)
        bold_count = sum(1 for td in tds if td.find("b"))
        if not header_row_done and bold_count >= 3:
            for td in tds:
                cls = td.get("class", [])
                if "hidden" in cls:
                    continue
                headers.append(td.get_text(strip=True).lower())
            header_row_done = True
            continue

        # Data rows
        visible = []
        comment = ""
        for td in tds:
            cls = td.get("class", [])
            if "hidden" in cls:
                comment = td.get_text(strip=True)
            else:
                visible.append(td.get_text(strip=True))

        if not visible or not headers:
            continue

        row_d = {}
        for i, h in enumerate(headers):
            row_d[h] = visible[i] if i < len(visible) else ""

        pos_id = row_d.get("position", "").strip()
        if not pos_id or pos_id.lower() in ("total", ""):
            continue

        profit     = parse_currency(row_d.get("profit", "0"))
        commission = parse_currency(row_d.get("commission", "0"))
        swap       = parse_currency(row_d.get("swap", "0"))

        trades.append({
            "open_time":   row_d.get("time", ""),
            "position_id": pos_id,
            "symbol":      row_d.get("symbol", ""),
            "type":        row_d.get("type", ""),
            "profit":      profit,
            "commission":  commission,
            "swap":        swap,
            "net":         round(profit + commission + swap, 2),
            "account_ref": comment,
        })

    log.info("parse_mt5_html: %d trades parsed from %s", len(trades), os.path.basename(html_path))
    if trades:
        open_times = [t["open_time"][:10] for t in trades if t["open_time"]]
        if open_times:
            log.info("  date range : %s → %s", min(open_times), max(open_times))
        sym_counts: dict = {}
        for t in trades:
            sym_counts[t["symbol"]] = sym_counts.get(t["symbol"], 0) + 1
        sym_summary = ", ".join(
            f"{s}:{n}" for s, n in sorted(sym_counts.items(), key=lambda x: -x[1])[:15]
        )
        log.info("  symbols    : %s", sym_summary)
        ref_missing = sum(1 for t in trades if not t["account_ref"])
        if ref_missing:
            log.warning("  %d trades have no account_ref / comment", ref_missing)
        grand_net = round(sum(t["net"] for t in trades), 2)
        log.info("  grand net  : %+.2f", grand_net)
    return trades


# ---------------------------------------------------------------------------
# DB lookup
# ---------------------------------------------------------------------------
def find_client_in_db(client_name):
    """Return (client_id, identity_dict, evaluations_list) or None."""
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT client_id, identity, evaluations FROM clients_data")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    search = client_name.lower().replace(" ", "")
    for row in rows:
        cid = row["client_id"]
        try:
            identity = json.loads(row["identity"] or "{}")
        except Exception:
            identity = {}

        candidates = [
            identity.get("name", ""),
            identity.get("display_name", ""),
            identity.get("client", ""),
            cid,
        ]
        for c in candidates:
            if c and c.lower().replace(" ", "") == search:
                try:
                    evals = json.loads(row["evaluations"] or "[]")
                except Exception:
                    evals = []
                return cid, identity, evals

    return None


# ---------------------------------------------------------------------------
# Phase → expected DB column  (mirrors get_field_name_for_phase in app.py)
# ---------------------------------------------------------------------------
def phase_to_column(phase_code, trade_number, account_number=""):
    pc = (phase_code or "").upper()
    tn = trade_number  # int or None
    is_mffu = str(account_number or "").upper().startswith("MFFU")

    if pc == "CH":
        if tn and 1 <= tn <= 10:
            return f"Hedge Result {tn}"
    elif pc == "FD":
        if tn is not None:
            if is_mffu:
                return f"Hedge Result {tn + 1}.1"
            else:
                n = max(tn, 1)
                return f"Hedge Result {n}.1"
    elif pc == "DD":
        if tn is not None:
            return f"Hedge Result {tn}.1"
    elif pc == "FA":
        # Farming: can't determine exact slot statically; mark as Hedge Day ?
        return "Hedge Day ?"
    return None


# ---------------------------------------------------------------------------
# Build comparison
# ---------------------------------------------------------------------------
def compare(trades, evaluations):
    """
    Groups MT5 trades by (account_sig, phase_code, trade_number).
    For each group:
      - Determines the expected DB column via phase_to_column()
      - Finds DB eval rows where Account Number signature matches
      - Fetches that specific column value from DB
      - Reports: MATCH, MISMATCH, or MISSING (account in DB but column empty/absent)
    Unmatched groups (account sig not in DB at all) are reported separately.
    """
    SKIP_COMMENT_KEYS = {"payout", "payment", "withdraw", "disburs"}

    # --- Parse every trade comment → aggregate by (sig, phase_code, trade_number) ---
    # key: (sig, phase_code, trade_number_or_None)
    # value: { acct, raw_ref, net, count, expected_col }
    group_map: dict = {}

    for t in trades:
        raw_ref = t["account_ref"] or ""
        if not raw_ref:
            continue
        if any(k in raw_ref.lower() for k in SKIP_COMMENT_KEYS):
            continue

        if _PARSER:
            parsed = _PARSER.parse(raw_ref)
            acct       = parsed.account_number if parsed.account_number else raw_ref
            phase_code = parsed.phase_code or ""
            trade_num  = parsed.trade_number
        else:
            acct = re.sub(r'_(CH|FD|DD|FA|UNK)(_\d{6})?(\d*)$', '', raw_ref, flags=re.IGNORECASE)
            m = re.search(r'_(CH|FD|DD|FA|UNK)_?(\d*)', raw_ref, re.IGNORECASE)
            phase_code = m.group(1).upper() if m else ""
            trade_num  = int(m.group(2)) if (m and m.group(2)) else None

        sig          = get_account_signature(acct)
        expected_col = phase_to_column(phase_code, trade_num, acct)

        # FA has no day number in the comment — group by trading date so each
        # day's net is compared to exactly one Hedge Day N column.
        if phase_code.upper() == "FA":
            day_label = (t.get("open_time") or "")[:10]   # e.g. "2026.03.06"
            key = (sig, phase_code, day_label)
        else:
            day_label = None
            key = (sig, phase_code, trade_num)

        trade_date = (t.get("open_time") or "")[:10]

        if key not in group_map:
            group_map[key] = {
                "sig": sig, "acct": acct, "raw_ref": raw_ref,
                "phase_code": phase_code, "trade_num": trade_num,
                "day_label": day_label,
                "expected_col": expected_col,
                "net": 0.0, "count": 0,
                "date_min": trade_date, "date_max": trade_date,
            }
        group_map[key]["net"]   += t["net"]
        group_map[key]["count"] += 1
        if trade_date:
            if not group_map[key]["date_min"] or trade_date < group_map[key]["date_min"]:
                group_map[key]["date_min"] = trade_date
            if not group_map[key]["date_max"] or trade_date > group_map[key]["date_max"]:
                group_map[key]["date_max"] = trade_date

    for key in group_map:
        group_map[key]["net"] = round(group_map[key]["net"], 2)

    log.info("compare(): %d trade groups built from %d comment refs",
             len(group_map), sum(g["count"] for g in group_map.values()))

    # --- Build sig → eval rows index from DB ---
    db_sig_index: dict = {}  # sig → list of (eval_idx, account_no)

    def _index(sig, idx, acct_no):
        db_sig_index.setdefault(sig, []).append((idx, acct_no))

    for idx, ev in enumerate(evaluations):
        if not isinstance(ev, dict):
            continue
        acct_no = (
            ev.get("Account Number")
            or ev.get("Account #")
            or ev.get("account_number")
            or ev.get("account_no")
            or ""
        )
        acct_no = str(acct_no).strip()
        if not acct_no:
            continue
        # Primary sig (first4 + last4 for full accounts)
        sig = get_account_signature(acct_no)
        _index(sig, idx, acct_no)
        # Secondary sig: first4 + last5 — matches MT5 truncated FNFT...29342 style
        # where the parser keeps the full 5-digit suffix instead of last-4
        if "..." not in acct_no and len(acct_no) > 8:
            alt_sig = (acct_no[:4] + acct_no[-5:]).lower()
            if alt_sig != sig:
                _index(alt_sig, idx, acct_no)

    log.info("  DB index  : %d unique account sigs across %d eval rows",
             len(db_sig_index), len(evaluations))

    # --- Classify each group ---
    matched_sigs   = set()
    exact_matches  = []
    mismatches     = []   # account found, expected column has a different value
    missing_col    = []   # account found, but expected column is empty / absent
    not_in_db      = []   # account signature not found in DB at all

    for key, info in sorted(group_map.items(), key=lambda x: x[1]["acct"].lower()):
        sig          = info["sig"]
        html_net     = info["net"]
        expected_col = info["expected_col"]

        log.debug("GROUP  sig=%-14s  phase=%-4s  col=%-22s  net=%+10.2f  trades=%d",
                  sig, info["phase_code"] or "?", expected_col or "Hedge Day ?",
                  html_net, info["count"])

        if sig not in db_sig_index:
            log.debug("  → NOT_IN_DB  acct=%s  sig=%s", info["acct"], sig)
            not_in_db.append(info)
            continue

        matched_sigs.add(sig)

        for eval_idx, acct_no in db_sig_index[sig]:
            ev = evaluations[eval_idx]

            if not expected_col or expected_col == "Hedge Day ?":
                # Farming: find the ONE Hedge Day N that matches this day's net.
                # Break as soon as an exact hit is found; otherwise track the
                # closest-value column as a single mismatch candidate.
                matched_col   = None
                best_mismatch = None
                best_diff     = float("inf")

                for n in range(1, 51):
                    col    = f"Hedge Day {n}"
                    db_val = parse_num(ev.get(col))
                    if db_val is None:
                        continue
                    diff = round(db_val - html_net, 2)
                    if abs(diff) < 0.02:
                        matched_col = col
                        log.debug("  → FA EXACT     acct=%s  col=%r  db=%.2f  mt5=%.2f",
                                  acct_no, col, db_val, html_net)
                        exact_matches.append({
                            **info, "eval_row": eval_idx, "account_no": acct_no,
                            "column": col, "db_value": db_val, "diff": 0.0,
                        })
                        break
                    if abs(diff) < abs(best_diff):
                        best_diff = diff
                        best_mismatch = {
                            **info, "eval_row": eval_idx, "account_no": acct_no,
                            "column": col, "db_value": db_val, "diff": diff,
                        }

                if matched_col is None:
                    if best_mismatch:
                        log.debug("  → FA MISMATCH  acct=%s  best_col=%r  db=%.2f  mt5=%.2f  diff=%+.2f",
                                  acct_no, best_mismatch["column"],
                                  best_mismatch["db_value"], html_net, best_mismatch["diff"])
                        mismatches.append(best_mismatch)
                    else:
                        log.debug("  → FA MISSING   acct=%s  no Hedge Day col has a value", acct_no)
                        missing_col.append({
                            **info, "eval_row": eval_idx, "account_no": acct_no,
                            "column": "Hedge Day ?", "db_value": None,
                        })
                continue

            db_val = parse_num(ev.get(expected_col))

            if db_val is None or db_val == 0:
                # Column empty — record as missing
                log.debug("  → MISSING   acct=%s  col=%r  db=%s  mt5=%+.2f",
                          acct_no, expected_col, db_val, html_net)
                missing_col.append({
                    **info,
                    "eval_row":   eval_idx,
                    "account_no": acct_no,
                    "column":     expected_col,
                    "db_value":   db_val,
                })
            else:
                diff  = round(db_val - html_net, 2)
                rec   = {**info, "eval_row": eval_idx, "account_no": acct_no,
                         "column": expected_col, "db_value": db_val, "diff": diff}
                if abs(diff) < 0.02:
                    log.debug("  → EXACT     acct=%s  col=%r  db=%.2f  mt5=%.2f",
                              acct_no, expected_col, db_val, html_net)
                else:
                    log.debug("  → MISMATCH  acct=%s  col=%r  db=%.2f  mt5=%.2f  diff=%+.2f",
                              acct_no, expected_col, db_val, html_net, diff)
                (exact_matches if abs(diff) < 0.02 else mismatches).append(rec)

    # --- Deduplicate: remove mismatches where the same (eval_row, column)
    #     already has an exact match.  This happens when two trade groups
    #     (e.g. different FD trade numbers) map to the same DB cell.
    #     The DB value is correct for one group; "fixing" it would break
    #     that exact match and just create an endless ping-pong cycle.
    exact_cells = {(r["eval_row"], r["column"]) for r in exact_matches}
    if exact_cells:
        before_n = len(mismatches)
        conflicts = [m for m in mismatches if (m["eval_row"], m["column"]) in exact_cells]
        mismatches = [m for m in mismatches if (m["eval_row"], m["column"]) not in exact_cells]
        if conflicts:
            log.info("  Removed %d phantom mismatch(es) — DB cell already exact for another group:",
                     len(conflicts))
            for c in conflicts:
                log.info("    CONFLICT  acct=%-30s  col=%-22s  db=%+10.2f  mt5=%+10.2f  (kept exact, skipped fix)",
                         c["account_no"], c["column"], c["db_value"], c["net"])

    log.info("compare() done: %d groups | %d matched sigs | not_in_db=%d | exact=%d | mismatches=%d | missing=%d",
             len(group_map), len(matched_sigs),
             len(not_in_db), len(exact_matches), len(mismatches), len(missing_col))

    if mismatches:
        log.info("  --- mismatches summary ---")
        for r in sorted(mismatches, key=lambda x: abs(x["diff"]), reverse=True):
            log.info("  MISMATCH  %-30s  %-22s  db=%+10.2f  mt5=%+10.2f  diff=%+10.2f",
                     r["account_no"], r["column"], r["db_value"], r["net"], r["diff"])
        total_diff = round(sum(r["diff"] for r in mismatches), 2)
        log.info("  total mismatch diff: %+.2f", total_diff)

    return group_map, matched_sigs, not_in_db, exact_matches, mismatches, missing_col


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def build_html(client_name, group_map, matched_sigs, not_in_db,
               exact_matches, mismatches, missing_col, trades,
               server_port=None):
    total_trades  = len(trades)
    grand_net     = round(sum(t["net"] for t in trades), 2)
    unique_groups = len(group_map)

    def phase_badge(pc, tn, day_label=None):
        if day_label and (pc or "").upper() == "FA":
            label = f"FA {day_label}"
        elif tn is not None:
            label = f"{pc}{tn}"
        else:
            label = pc or "?"
        colors = {"CH": "#60a5fa", "FD": "#a78bfa", "DD": "#f472b6",
                  "FA": "#34d399", "UNK": "#94a3b8"}
        c = colors.get((pc or "").upper(), "#94a3b8")
        return f'<span style="background:rgba({int(c[1:3],16)},{int(c[3:5],16)},{int(c[5:7],16)},0.15);color:{c};border-radius:5px;padding:1px 7px;font-size:0.72rem;font-weight:600">{label}</span>'

    # --- Mismatch rows ---
    mismatch_rows = ""
    for r in sorted(mismatches, key=lambda x: (x["account_no"], x["phase_code"] or "", x.get("day_label") or str(x["trade_num"] or 0))):
        mismatch_rows += f"""
        <tr>
          <td class="ref">{r['account_no']}</td>
          <td class="ref small">{r['raw_ref']}</td>
          <td>{phase_badge(r['phase_code'], r['trade_num'], r.get('day_label'))}</td>
          <td class="col-name">{r['column']}</td>
          <td class="num {'pos' if r['db_value'] >= 0 else 'neg'}">${r['db_value']:,.2f}</td>
          <td class="num {'pos' if r['net'] >= 0 else 'neg'}">${r['net']:,.2f}</td>
          <td class="num {'pos' if r['diff'] >= 0 else 'neg'}">${r['diff']:+,.2f}</td>
          <td class="small muted">row {r['eval_row']}</td>
        </tr>"""
    if not mismatch_rows:
        mismatch_rows = '<tr><td colspan="8" class="empty">No mismatches ✓</td></tr>'

    total_diff   = round(sum(r["diff"]     for r in mismatches), 2)
    total_db     = round(sum(r["db_value"] for r in mismatches), 2)
    total_mt5    = round(sum(r["net"]      for r in mismatches), 2)
    diff_cls     = 'pos' if total_diff >= 0 else 'neg'
    db_cls       = 'pos' if total_db   >= 0 else 'neg'
    mt5_cls      = 'pos' if total_mt5  >= 0 else 'neg'
    mismatch_foot = f"""
      <tr>
        <td colspan="4" style="color:#64748b;font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase">Total ({len(mismatches)} rows)</td>
        <td class="num {db_cls}">${total_db:,.2f}</td>
        <td class="num {mt5_cls}">${total_mt5:,.2f}</td>
        <td class="num {diff_cls}">${total_diff:+,.2f}</td>
        <td></td>
      </tr>"""

    # --- Missing column rows ---
    missing_rows = ""
    for r in sorted(missing_col, key=lambda x: (x["account_no"], x["phase_code"] or "")):
        db_display = f"${r['db_value']:,.2f}" if r['db_value'] is not None else '<span class="muted">empty</span>'
        missing_rows += f"""
        <tr>
          <td class="ref">{r['account_no']}</td>
          <td class="ref small">{r['raw_ref']}</td>
          <td>{phase_badge(r['phase_code'], r['trade_num'], r.get('day_label'))}</td>
          <td class="col-name">{r['column']}</td>
          <td class="num muted">{db_display}</td>
          <td class="num {'pos' if r['net'] >= 0 else 'neg'}">${r['net']:,.2f}</td>
          <td class="small muted">row {r['eval_row']}</td>
        </tr>"""
    if not missing_rows:
        missing_rows = '<tr><td colspan="7" class="empty">No missing columns ✓</td></tr>'

    missing_net_total = round(sum(r["net"] for r in missing_col), 2)
    missing_net_cls   = 'pos' if missing_net_total >= 0 else 'neg'
    missing_foot = f"""
      <tr>
        <td colspan="5" style="color:#64748b;font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase">Total ({len(missing_col)} rows)</td>
        <td class="num {missing_net_cls}">${missing_net_total:,.2f}</td>
        <td></td>
      </tr>"""

    # --- Not in DB rows ---
    not_in_db_rows = ""
    for r in sorted(not_in_db, key=lambda x: (x.get("date_min") or "", x["acct"].lower())):
        d_min = r.get("date_min") or ""
        d_max = r.get("date_max") or ""
        date_display = d_min if (not d_max or d_min == d_max) else f"{d_min} — {d_max}"
        not_in_db_rows += f"""
        <tr data-date="{d_min}">
          <td class="ref">{r['acct']}</td>
          <td class="ref small">{r['raw_ref']}</td>
          <td>{phase_badge(r['phase_code'], r['trade_num'], r.get('day_label'))}</td>
          <td class="col-name muted">{r['expected_col'] or '—'}</td>
          <td class="small muted">{date_display}</td>
          <td class="num {'pos' if r['net'] >= 0 else 'neg'}">${r['net']:,.2f}</td>
          <td class="num">{r['count']}</td>
        </tr>"""
    if not not_in_db_rows:
        not_in_db_rows = '<tr><td colspan="7" class="empty">All accounts found in DB ✓</td></tr>'

    not_in_db_net_total = round(sum(r["net"] for r in not_in_db), 2)
    not_in_db_net_cls   = 'pos' if not_in_db_net_total >= 0 else 'neg'
    not_in_db_foot = f"""
      <tr>
        <td colspan="5" style="color:#64748b;font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase">Total ({len(not_in_db)} rows)</td>
        <td class="num {not_in_db_net_cls}">${not_in_db_net_total:,.2f}</td>
        <td></td>
      </tr>"""

    # --- Exact match rows (collapsed) ---
    exact_rows = ""
    for r in sorted(exact_matches, key=lambda x: (x["account_no"], x["column"])):
        exact_rows += f"""
        <tr>
          <td class="ref">{r['account_no']}</td>
          <td>{phase_badge(r['phase_code'], r['trade_num'], r.get('day_label'))}</td>
          <td class="col-name">{r['column']}</td>
          <td class="num pos">${r['db_value']:,.2f}</td>
          <td class="num pos">${r['net']:,.2f}</td>
          <td class="small muted">row {r['eval_row']}</td>
        </tr>"""
    if not exact_rows:
        exact_rows = '<tr><td colspan="6" class="empty">No exact matches found</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MT5 vs DB — {client_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0a0f1e; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; padding: 32px; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; color: #60a5fa; margin-bottom: 4px; }}
    h2 {{ font-size: 0.85rem; font-weight: 500; color: #94a3b8; margin: 28px 0 10px;
          letter-spacing: 0.08em; text-transform: uppercase; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px; }}
    .stats {{ display: flex; gap: 12px; margin: 16px 0 28px; flex-wrap: wrap; }}
    .stat {{ background: #111827; border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 13px 18px; min-width: 120px; }}
    .stat-label {{ font-size: 0.68rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; }}
    .stat-value {{ font-size: 1.3rem; font-weight: 700; color: #e2e8f0; margin-top: 4px; }}
    .stat-value.green {{ color: #4ade80; }} .stat-value.red {{ color: #f87171; }} .stat-value.blue {{ color: #60a5fa; }}
    /* Search bar */
    .search-bar {{ position: sticky; top: 0; z-index: 100; background: #0a0f1e;
                   padding: 10px 0 14px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); margin-bottom: 22px; }}
    .search-bar input {{ background: #111827; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;
                         color: #e2e8f0; font-size: 0.87rem; padding: 7px 14px; width: 220px; outline: none; }}
    .search-bar input:focus {{ border-color: #60a5fa; box-shadow: 0 0 0 2px rgba(96,165,250,0.2); }}
    .search-bar input::placeholder {{ color: #475569; }}
    .search-bar .search-count {{ font-size: 0.78rem; color: #64748b; }}
    .search-bar .search-count span {{ color: #60a5fa; font-weight: 600; }}
    tr.search-hidden {{ display: none; }}
    tr.search-highlight {{ background: rgba(96,165,250,0.12) !important; outline: 1px solid rgba(96,165,250,0.35); }}
    .btn {{ border: none; border-radius: 7px; padding: 6px 14px; font-size: 0.8rem;
             font-weight: 600; cursor: pointer; transition: opacity 0.15s, background 0.2s; }}
    .btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .btn-green {{ background: #166534; color: #4ade80; border: 1px solid rgba(74,222,128,0.2); }}
    .btn-green:hover:not(:disabled) {{ background: #14532d; }}
    .btn-blue  {{ background: #1e3a5f; color: #60a5fa; border: 1px solid rgba(96,165,250,0.2); }}
    .btn-blue:hover:not(:disabled)  {{ background: #1e3a8a; }}
    #fix-status {{ font-size: 0.78rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-bottom: 6px; }}
    th {{ background: #0d1628; color: #94a3b8; text-transform: uppercase; font-size: 0.67rem;
          letter-spacing: 0.08em; padding: 9px 12px; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; }}
    td {{ padding: 7px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); }}
    tr:hover {{ background: rgba(255,255,255,0.025); }}
    .num   {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .ref   {{ color: #a5b4fc; font-family: monospace; }}
    .col-name {{ color: #e2e8f0; }}
    .small {{ font-size: 0.74rem; }}
    .muted {{ color: #64748b; }}
    .pos   {{ color: #4ade80; }} .neg {{ color: #f87171; }}
    tfoot td {{ background: #0d1628; border-top: 1px solid rgba(255,255,255,0.12);
                font-weight: 600; color: #e2e8f0; padding: 9px 12px; }}
    .empty {{ text-align: center; color: #64748b; padding: 18px; font-style: italic; }}
    details {{ margin-bottom: 32px; }}
    details summary {{ cursor: pointer; padding: 8px 0; color: #64748b; font-size: 0.8rem;
                       user-select: none; border-bottom: 1px solid rgba(255,255,255,0.04); margin-bottom: 10px; }}
    details summary:hover {{ color: #94a3b8; }}
    /* Sort indicators */
    thead th {{ cursor: pointer; transition: color 0.15s; white-space: nowrap; }}
    thead th:hover {{ color: #e2e8f0; }}
    th[data-sort="asc"]::after  {{ content: ' ↑'; color: #60a5fa; font-size: 0.65rem; }}
    th[data-sort="desc"]::after {{ content: ' ↓'; color: #60a5fa; font-size: 0.65rem; }}
    /* Month filter toolbar */
    .table-toolbar {{ display: flex; align-items: center; gap: 10px; margin: -4px 0 10px; flex-wrap: wrap; }}
    .table-toolbar select {{ background: #111827; border: 1px solid rgba(255,255,255,0.1); border-radius: 7px;
                              color: #e2e8f0; font-size: 0.8rem; padding: 5px 12px; outline: none; cursor: pointer; }}
    .table-toolbar select:focus {{ border-color: #60a5fa; box-shadow: 0 0 0 2px rgba(96,165,250,0.2); }}
    .table-toolbar select option {{ background: #111827; }}
    .filter-count {{ font-size: 0.75rem; color: #64748b; }}
    tr.month-hidden {{ display: none; }}
  </style>
</head>
<body>
  <h1>MT5 Report vs Database — {client_name}</h1>

  <div class="search-bar">
    <input id="acct-search" type="text" placeholder="Search last 5 digits…" maxlength="20" autocomplete="off" spellcheck="false">
    <div class="search-count" id="search-count"></div>
    <button onclick="document.getElementById('acct-search').value=''; runSearch();"
      style="background:none;border:1px solid rgba(255,255,255,0.1);color:#64748b;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:0.75rem;">Clear</button>
    <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
      <span id="fix-status"></span>
      {'<button id="fix-btn" class="btn btn-green" onclick="fixValues()">Replace Values</button>' if mismatches and server_port else ''}
      {'<button id="fill-btn" class="btn" style="background:#1e3a5f;color:#60a5fa;" onclick="fillMissing()">Fill Missing</button>' if missing_col and server_port else ''}
      {'<button class="btn btn-blue" onclick="reloadReport()">Reload</button>' if server_port else ''}
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="stat-label">Trades in HTML</div><div class="stat-value blue">{total_trades:,}</div></div>
    <div class="stat"><div class="stat-label">Comment Groups</div><div class="stat-value blue">{unique_groups}</div></div>
    <div class="stat"><div class="stat-label">Matched in DB</div><div class="stat-value green">{len(matched_sigs)}</div></div>
    <div class="stat"><div class="stat-label">Not in DB</div><div class="stat-value {'red' if not_in_db else 'green'}">{len(not_in_db)}</div></div>
    <div class="stat"><div class="stat-label">Mismatches</div><div class="stat-value {'red' if mismatches else 'green'}">{len(mismatches)}</div></div>
    <div class="stat"><div class="stat-label">Missing Cols</div><div class="stat-value {'red' if missing_col else 'green'}">{len(missing_col)}</div></div>
    <div class="stat"><div class="stat-label">Exact Matches</div><div class="stat-value green">{len(exact_matches)}</div></div>
    <div class="stat"><div class="stat-label">Grand Net P&amp;L</div><div class="stat-value {'green' if grand_net >= 0 else 'red'}">${grand_net:,.2f}</div></div>
  </div>

  <h2>⚠ Value Mismatches — account in DB, but column value differs from MT5 net</h2>
  <table>
    <thead><tr><th>DB Account No.</th><th>MT5 Comment</th><th>Phase</th><th>Expected Column</th>
      <th style="text-align:right">DB Value</th><th style="text-align:right">MT5 Net</th>
      <th style="text-align:right">Diff</th><th>Location</th></tr></thead>
    <tbody>{mismatch_rows}</tbody>
    <tfoot>{mismatch_foot}</tfoot>
  </table>

  <h2>⚠ Missing / Empty — account in DB, expected column not filled</h2>
  <table>
    <thead><tr><th>DB Account No.</th><th>MT5 Comment</th><th>Phase</th><th>Expected Column</th>
      <th style="text-align:right">Current DB Value</th><th style="text-align:right">MT5 Net (should be)</th>
      <th>Location</th></tr></thead>
    <tbody>{missing_rows}</tbody>
    <tfoot>{missing_foot}</tfoot>
  </table>

  <h2>✗ Not in DB — comment account not found in any evaluation row</h2>
  <div class="table-toolbar">
    <select id="month-filter"><option value="">All months</option></select>
    <span class="filter-count" id="month-filter-count"></span>
  </div>
  <table id="not-in-db-tbl">
    <thead><tr><th>Account (parsed)</th><th>MT5 Comment</th><th>Phase</th>
      <th>Expected Column</th><th>Date(s)</th><th style="text-align:right">MT5 Net</th><th>Trades</th></tr></thead>
    <tbody>{not_in_db_rows}</tbody>
    <tfoot>{not_in_db_foot}</tfoot>
  </table>

  <details>
    <summary>▸ {len(exact_matches)} exact match(es) — DB value equals MT5 net</summary>
    <table>
      <thead><tr><th>Account No.</th><th>Phase</th><th>Column</th>
        <th style="text-align:right">DB Value</th><th style="text-align:right">MT5 Net</th><th>Location</th></tr></thead>
      <tbody>{exact_rows}</tbody>
    </table>
  </details>

  <script>
    // ── Month filter ──────────────────────────────────────────────────────────
    function buildMonthFilter() {{
      const rows = document.querySelectorAll('#not-in-db-tbl tbody tr[data-date]');
      const months = new Set();
      rows.forEach(r => {{
        const d = r.dataset.date || '';
        if (d.length >= 7) months.add(d.substring(0, 7)); // "2026.03"
      }});
      const sel = document.getElementById('month-filter');
      [...months].sort().forEach(m => {{
        const [yr, mo] = m.split('.');
        const label = new Date(parseInt(yr), parseInt(mo) - 1)
                        .toLocaleString('default', {{ month: 'short', year: 'numeric' }});
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = label;
        sel.appendChild(opt);
      }});
    }}

    function applyMonthFilter() {{
      const val = document.getElementById('month-filter').value;
      const rows = document.querySelectorAll('#not-in-db-tbl tbody tr[data-date]');
      let visible = 0;
      rows.forEach(r => {{
        const d = r.dataset.date || '';
        const hide = val && !d.startsWith(val);
        r.classList.toggle('month-hidden', hide);
        if (!hide) visible++;
      }});
      const cnt = document.getElementById('month-filter-count');
      cnt.textContent = val ? visible + ' row' + (visible !== 1 ? 's' : '') : '';
      runSearch(); // re-apply search count after filter changes
    }}

    document.getElementById('month-filter').addEventListener('change', applyMonthFilter);

    // ── Sortable tables ───────────────────────────────────────────────────────
    function initSortable() {{
      const sortState = new WeakMap();
      document.querySelectorAll('table').forEach(table => {{
        const ths = table.querySelectorAll('thead th');
        ths.forEach((th, idx) => {{
          th.addEventListener('click', () => {{
            const cur = sortState.get(th) || 'none';
            const asc = cur !== 'asc';
            ths.forEach(t => {{ sortState.set(t, 'none'); delete t.dataset.sort; }});
            sortState.set(th, asc ? 'asc' : 'desc');
            th.dataset.sort = asc ? 'asc' : 'desc';
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'))
                              .filter(r => !r.querySelector('.empty'));
            rows.sort((a, b) => {{
              const aText = (a.cells[idx]?.textContent || '').trim();
              const bText = (b.cells[idx]?.textContent || '').trim();
              const aNum = parseFloat(aText.replace(/[$,+% ]/g, ''));
              const bNum = parseFloat(bText.replace(/[$,+% ]/g, ''));
              if (!isNaN(aNum) && !isNaN(bNum)) return asc ? aNum - bNum : bNum - aNum;
              return asc ? aText.localeCompare(bText) : bText.localeCompare(aText);
            }});
            rows.forEach(r => tbody.appendChild(r));
          }});
        }});
      }});
    }}

    // ── Account search ────────────────────────────────────────────────────────
    function runSearch() {{
      const raw   = document.getElementById('acct-search').value.trim();
      const query = raw.toLowerCase();
      const allRows = document.querySelectorAll('tbody tr');
      let hits = 0;

      allRows.forEach(tr => {{
        if (tr.querySelector('.empty')) return;
        const cells = tr.querySelectorAll('td');
        if (!cells.length) return;
        const text = Array.from(cells).slice(0, 2).map(c => c.textContent.toLowerCase()).join(' ');
        const match = query && text.includes(query);
        if (query === '') {{
          tr.classList.remove('search-hidden', 'search-highlight');
        }} else if (match) {{
          tr.classList.remove('search-hidden');
          tr.classList.add('search-highlight');
          const det = tr.closest('details');
          if (det && !det.open) det.open = true;
          if (!tr.classList.contains('month-hidden')) hits++;
        }} else {{
          tr.classList.add('search-hidden');
          tr.classList.remove('search-highlight');
        }}
      }});

      const countEl = document.getElementById('search-count');
      if (!query) {{
        countEl.innerHTML = '';
      }} else {{
        countEl.innerHTML = hits
          ? '<span>' + hits + '</span> row' + (hits !== 1 ? 's' : '') + ' found'
          : 'No rows matched';
        const first = document.querySelector('tr.search-highlight:not(.month-hidden)');
        if (first) first.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }}

    document.getElementById('acct-search').addEventListener('input', runSearch);
    document.getElementById('acct-search').addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') {{ this.value = ''; runSearch(); }}
      if (e.key === 'Enter') {{
        const hits = Array.from(document.querySelectorAll('tr.search-highlight:not(.month-hidden):not(.search-hidden)'));
        if (!hits.length) return;
        const pivot = hits.findIndex(r => r.getBoundingClientRect().top > 80);
        const next = hits[pivot === -1 ? 0 : pivot];
        if (next) next.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }});

    // ── Fix + Reload ────────────────────────────────────────────────────────
    function fixValues() {{
      const btn = document.getElementById('fix-btn');
      const status = document.getElementById('fix-status');
      if (!btn) return;
      btn.disabled = true;
      btn.textContent = 'Applying…';
      status.style.color = '#64748b';
      status.textContent = '';
      fetch('http://localhost:{server_port}/fix', {{ method: 'POST' }})
        .then(r => r.json())
        .then(data => {{
          btn.textContent = '✓ Done';
          btn.style.background = '#14532d';
          status.style.color = '#4ade80';
          status.textContent = data.fixed + ' value' + (data.fixed !== 1 ? 's' : '') + ' replaced — reloading…';
          setTimeout(() => {{ window.location.href = 'http://localhost:{server_port}/'; }}, 1200);
        }})
        .catch(() => {{
          btn.textContent = 'Error';
          btn.style.background = '#7f1d1d';
          btn.style.color = '#f87171';
          btn.disabled = false;
          status.style.color = '#f87171';
          status.textContent = 'Could not connect to local server';
        }});
    }}

    function fillMissing() {{
      const btn = document.getElementById('fill-btn');
      const status = document.getElementById('fix-status');
      if (!btn) return;
      btn.disabled = true;
      btn.textContent = 'Filling…';
      status.style.color = '#64748b';
      status.textContent = '';
      fetch('http://localhost:{server_port}/fill', {{ method: 'POST' }})
        .then(r => r.json())
        .then(data => {{
          btn.textContent = '✓ Filled';
          btn.style.background = '#14532d';
          btn.style.color = '#4ade80';
          status.style.color = '#4ade80';
          status.textContent = data.filled + ' empty cell' + (data.filled !== 1 ? 's' : '') + ' filled — reloading…';
          setTimeout(() => {{ window.location.href = 'http://localhost:{server_port}/'; }}, 1200);
        }})
        .catch(() => {{
          btn.textContent = 'Error';
          btn.style.background = '#7f1d1d';
          btn.style.color = '#f87171';
          btn.disabled = false;
          status.style.color = '#f87171';
          status.textContent = 'Could not connect to local server';
        }});
    }}

    function reloadReport() {{
      window.location.href = 'http://localhost:{server_port}/';
    }}

    // Init
    buildMonthFilter();
    initSortable();
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Recalculate hedge nets + statistics (mirrors dashboard logic)
# ---------------------------------------------------------------------------
def _recalculate_hedge_nets(evaluations):
    """Recalculate Hedge Net and Hedge Net.1 for every evaluation row."""
    def _num(val):
        if val is None or str(val).strip() in ('', '-'):
            return 0.0
        try:
            return float(str(val).replace('$', '').replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0

    def _is_blank(val):
        return val is None or str(val).strip() in ('', '-')

    for ev in (evaluations or []):
        # Hedge Net (Phase 1): -Fee + HR1..HR5  only when HR1 present AND Status P1 == "Fail"
        status_p1 = str(ev.get('Status P1', '')).strip()
        if _is_blank(ev.get('Hedge Result 1')) or status_p1 != 'Fail':
            ev['Hedge Net'] = ''
        else:
            fee = _num(ev.get('Fee'))
            hr_sum = sum(_num(ev.get(f'Hedge Result {i}')) for i in range(1, 6))
            ev['Hedge Net'] = -fee + hr_sum

        # Hedge Net.1 (Funded)
        status = str(ev.get('Status') or ev.get('Status Funded', '')).strip()
        sum_phase1 = sum(_num(ev.get(f'Hedge Result {i}')) for i in range(1, 6))
        sum_funded = sum(_num(ev.get(c)) for c in [
            'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
            'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
        ])
        fee = _num(ev.get('Fee'))
        activation_fee = _num(ev.get('Activation Fee'))

        if status == 'Completed':
            sum_payouts = sum(_num(ev.get(f'Payout {i}')) for i in range(1, 7))
            sum_days = sum(_num(ev.get(f'Hedge Day {i}')) for i in range(1, 51))
            ev['Hedge Net.1'] = sum_payouts + sum_funded + sum_phase1 - fee - activation_fee + sum_days
        elif status == 'Fail':
            ev['Hedge Net.1'] = sum_funded + sum_phase1 - fee - activation_fee
        else:
            ev['Hedge Net.1'] = ''

    return evaluations


def _recalculate_and_save(client_id, evals):
    """Recalculate Hedge Net/Net.1, statistics, discrepancy, and save to DB."""
    evals = _recalculate_hedge_nets(evals)
    log.info("recalculate: hedge nets updated for client_id=%s", client_id)

    if calculate_statistics is None:
        # Can't recalculate stats — just save updated evals
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE clients_data SET evaluations = %s WHERE client_id = %s",
                    (json.dumps(evals), client_id))
        conn.commit()
        cur.close(); conn.close()
        log.warning("recalculate: skipped statistics (calculate_statistics unavailable)")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Fetch existing statistics to preserve MT5-derived hedging review fields
    cur.execute("SELECT statistics FROM clients_data WHERE client_id = %s", (client_id,))
    row = cur.fetchone()
    existing_stats = {}
    if row and row[0]:
        existing_stats = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    existing_hr = existing_stats.get('hedging_review', {})

    # Recalculate statistics from updated evaluations
    new_stats = calculate_statistics(evals)

    # Preserve MT5-derived fields (deposits, withdrawals, balance, actual)
    new_hr = new_stats.setdefault('hedging_review', {})
    new_hr['total_deposits'] = existing_hr.get('total_deposits', 0)
    new_hr['total_withdrawals'] = existing_hr.get('total_withdrawals', 0)
    new_hr['current_balance'] = existing_hr.get('current_balance', 0)
    new_hr['actual_hedging_results'] = existing_hr.get('actual_hedging_results', 0)

    # Preserve historical account fields
    hist = existing_hr.get('historical_accounts')
    if hist:
        new_hr['historical_accounts'] = hist
        new_hr['historical_deposits'] = existing_hr.get('historical_deposits', 0)
        new_hr['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
        new_hr['historical_balance'] = existing_hr.get('historical_balance', 0)

    # Recalculate discrepancy = actual - sheet
    new_hr['discrepancy'] = round(
        new_hr['actual_hedging_results'] - new_hr.get('sheet_hedging_results', 0), 2
    )
    disc = new_hr['discrepancy']

    # Recalculate net_profit for both sections
    for sk in ["profitability_completed", "cashflow_inprogress"]:
        sec = new_stats[sk]
        sec["net_profit"] = round(
            sec["payouts"] + sec["hedging_results"] + sec["farming_results"]
            - sec["challenge_fees"] + disc, 2
        )

    # Save updated evaluations + statistics
    cur.execute(
        "UPDATE clients_data SET evaluations = %s, statistics = %s WHERE client_id = %s",
        (json.dumps(evals), json.dumps(new_stats), client_id),
    )
    conn.commit()
    cur.close(); conn.close()
    log.info("recalculate: statistics updated — discrepancy=%.2f  net_profit(completed)=%.2f  net_profit(cashflow)=%.2f",
             disc,
             new_stats['profitability_completed']['net_profit'],
             new_stats['cashflow_inprogress']['net_profit'])


# ---------------------------------------------------------------------------
# Apply fixes to DB
# ---------------------------------------------------------------------------
def apply_fixes_to_db(client_id, mismatches_list):
    """Overwrite the expected column in each mismatched eval row with the MT5 net value."""
    log.info("apply_fixes_to_db: client_id=%s  rows_to_fix=%d", client_id, len(mismatches_list))
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    # Fetch current evaluations
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = %s", (client_id,))
    row = cur.fetchone()
    if row is None:
        cur.close(); conn.close()
        return []

    evals = row[0]
    if isinstance(evals, str):
        evals = json.loads(evals)

    fixed = []
    for r in mismatches_list:
        eval_idx = r["eval_row"]
        col      = r["column"]
        new_val  = r["net"]
        old_val  = r["db_value"]
        if 0 <= eval_idx < len(evals) and isinstance(evals[eval_idx], dict):
            evals[eval_idx][col] = str(new_val)
            log.info("  FIX  row=%-4d  col=%-22r  old=%s → new=%+.2f",
                     eval_idx, col, old_val, new_val)
            fixed.append({"eval_row": eval_idx, "column": col,
                          "old": old_val, "new": new_val})
        else:
            log.warning("  SKIP row=%d  out of range or not a dict", eval_idx)

    cur.execute(
        "UPDATE clients_data SET evaluations = %s WHERE client_id = %s",
        (json.dumps(evals), client_id),
    )
    conn.commit()
    cur.close(); conn.close()
    log.info("apply_fixes_to_db: committed %d fix(es) for client_id=%s", len(fixed), client_id)

    # Recalculate hedge nets + statistics after fixing values
    if fixed:
        _recalculate_and_save(client_id, evals)

    return fixed


def apply_missing_to_db(client_id, missing_list):
    """Fill empty/absent columns with the MT5 net value."""
    log.info("apply_missing_to_db: client_id=%s  rows_to_fill=%d", client_id, len(missing_list))
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = %s", (client_id,))
    row = cur.fetchone()
    if row is None:
        cur.close(); conn.close()
        return []

    evals = row[0]
    if isinstance(evals, str):
        evals = json.loads(evals)

    filled = []
    for r in missing_list:
        eval_idx = r["eval_row"]
        col      = r["column"]
        new_val  = r["net"]
        if col == "Hedge Day ?":
            log.debug("  SKIP  row=%d  col=%r  (unresolved FA day)", eval_idx, col)
            continue
        if 0 <= eval_idx < len(evals) and isinstance(evals[eval_idx], dict):
            evals[eval_idx][col] = str(new_val)
            log.info("  FILL  row=%-4d  col=%-22r  val=%+.2f", eval_idx, col, new_val)
            filled.append({"eval_row": eval_idx, "column": col, "new": new_val})
        else:
            log.warning("  SKIP row=%d  out of range or not a dict", eval_idx)

    if filled:
        cur.execute(
            "UPDATE clients_data SET evaluations = %s WHERE client_id = %s",
            (json.dumps(evals), client_id),
        )
        conn.commit()
    cur.close(); conn.close()
    log.info("apply_missing_to_db: committed %d fill(s) for client_id=%s", len(filled), client_id)

    # Recalculate hedge nets + statistics after filling values
    if filled:
        _recalculate_and_save(client_id, evals)

    return filled


def find_free_port(start=5757):
    for port in range(start, start + 50):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("localhost", port))
            s.close()
            return port
        except OSError:
            continue
    return start


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python scripts/_compare_mt5_vs_db.py "Rob Madsen"')

    client_name = " ".join(sys.argv[1:]).strip()
    file_slug   = client_name.replace(" ", "_")
    html_path   = os.path.join(ROOT, "mt5_reports", f"{file_slug}.html")

    if not os.path.exists(html_path):
        sys.exit(f"ERROR: Report not found at {html_path}")

    log.info("=" * 70)
    log.info("START  client=%r", client_name)
    log.info("       html  =%s", html_path)
    log.info("       log   =%s", _LOG_FILE)

    PORT = find_free_port(5757)

    # Shared mutable state accessible inside the HTTP handler
    state = {"html": b"", "cid": None, "mismatches": [], "missing": []}

    def run_compare():
        log.info("-" * 70)
        log.info("RUN COMPARE  client=%r", client_name)
        log.info("Parsing MT5 HTML...")
        trades = parse_mt5_html(html_path)

        log.info("Looking up client in DB...")
        result = find_client_in_db(client_name)
        if result is None:
            log.error("Client %r not found in database.", client_name)
            return

        cid, identity, evaluations = result
        log.info("  Found: client_id=%s  eval_rows=%d", cid, len(evaluations))
        state["cid"] = cid

        log.info("Comparing...")
        group_map, matched_sigs, not_in_db, exact_matches, mismatches, missing_col = compare(trades, evaluations)
        state["mismatches"] = mismatches
        state["missing"] = missing_col

        log.info("  Comment groups       : %d", len(group_map))
        log.info("  Matched in DB        : %d", len(matched_sigs))
        log.info("  Not in DB            : %d", len(not_in_db))
        log.info("  Exact matches        : %d", len(exact_matches))
        log.info("  Mismatches           : %d", len(mismatches))
        log.info("  Missing columns      : %d", len(missing_col))

        html = build_html(client_name, group_map, matched_sigs, not_in_db,
                          exact_matches, mismatches, missing_col, trades,
                          server_port=PORT)
        state["html"] = html.encode("utf-8")
        log.info("  Report ready → http://localhost:%d/", PORT)

    run_compare()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = state["html"]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/reload":
                run_compare()
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/fix":
                cid = state["cid"]
                mms = state["mismatches"]
                if not cid or not mms:
                    body = json.dumps({"fixed": 0, "error": "Nothing to fix"}).encode()
                    log.warning("/fix called but nothing to fix (cid=%s, mms=%d)", cid, len(mms) if mms else 0)
                else:
                    fixed = apply_fixes_to_db(cid, mms)
                    run_compare()   # regenerate HTML from updated DB
                    body  = json.dumps({"fixed": len(fixed)}).encode()
                    log.info("/fix applied %d fix(es) to DB for client_id=%s", len(fixed), cid)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/fill":
                cid = state["cid"]
                mis = state["missing"]
                if not cid or not mis:
                    body = json.dumps({"filled": 0, "error": "Nothing to fill"}).encode()
                    log.warning("/fill called but nothing to fill (cid=%s, mis=%d)", cid, len(mis) if mis else 0)
                else:
                    filled = apply_missing_to_db(cid, mis)
                    run_compare()
                    body = json.dumps({"filled": len(filled)}).encode()
                    log.info("/fill wrote %d missing value(s) to DB for client_id=%s", len(filled), cid)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.end_headers()

        def log_message(self, fmt, *args):
            log.debug("HTTP %s  %s", self.address_string(), fmt % args)

    server = HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    log.info("Server running → http://localhost:%d/  (Ctrl+C to stop)", PORT)
    webbrowser.open(f"http://localhost:{PORT}/")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        log.info("Server stopped.")
