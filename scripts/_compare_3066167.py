"""
Compare MT5 History Report (3066167 / Robert Madsen) vs Google Sheet.
Adapted from _compare_mt5_sheet.py for this report's format.
"""
import re, csv, io, sys
from datetime import datetime
from collections import defaultdict
from bs4 import BeautifulSoup
import requests


# ─── Helpers ───────────────────────────────────────────────────
def parse_currency(val):
    """Parse MT5 currency: '49 700.00' → 49700.0, '- 131.45' → -131.45"""
    if not val or not val.strip():
        return 0.0
    s = val.replace('\xa0', ' ').strip()
    s = re.sub(r'[−–]', '-', s)
    s = re.sub(r'-\s+', '-', s)
    s = s.replace(' ', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_sheet_currency(val):
    """Parse sheet currency: '$736', '-$2,302', '($500)' → float or None."""
    if not val or not val.strip():
        return None
    s = val.strip()
    if s.lower() in ('pass', 'farming', 'n/a', '-', '', 'fail', 'breach'):
        return None
    neg = '(' in s or s.startswith('-')
    s = re.sub(r'[^0-9.]', '', s)
    if not s:
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


# ─── Parse MT5 HTML ────────────────────────────────────────────
def parse_mt5_report(html_path):
    with open(html_path, 'r', encoding='utf-16') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    table = soup.find('table')
    rows = table.find_all('tr')
    print(f"Total <tr> rows in table: {len(rows)}")

    sections = {}
    current_section = None
    current_headers = []
    section_rows = []

    for row in rows:
        tds = row.find_all(['td', 'th'])
        if not tds:
            continue

        first = tds[0]
        if first.get('colspan'):
            text = first.get_text(strip=True)
            if text in ('Positions', 'Orders', 'Deals'):
                if current_section and section_rows:
                    sections[current_section] = {'headers': current_headers, 'rows': section_rows}
                current_section = text.lower()
                current_headers = []
                section_rows = []
                continue
            elif current_section and text in ('Balance:', 'Credit Facility:', 'Floating P/L:', 'Equity:', 'Results'):
                if section_rows:
                    sections[current_section] = {'headers': current_headers, 'rows': section_rows}
                current_section = None
                continue

        if current_section is None:
            continue

        bold_count = sum(1 for td in tds if td.find('b'))
        if not current_headers and bold_count >= len(tds) // 2 and bold_count >= 3:
            for td in tds:
                cls = td.get('class', [])
                if 'hidden' in cls:
                    continue
                current_headers.append(td.get_text(strip=True))
            continue

        visible = []
        hidden_val = None
        for td in tds:
            cls = td.get('class', [])
            if 'hidden' in cls:
                hidden_val = td.get_text(strip=True)
                continue
            visible.append(td.get_text(strip=True))
        if hidden_val is not None:
            visible.append(hidden_val)
        section_rows.append(visible)

    if current_section and section_rows:
        sections[current_section] = {'headers': current_headers, 'rows': section_rows}

    for name, sec in sections.items():
        print(f"  Section '{name}': {len(sec['headers'])} headers, {len(sec['rows'])} data rows")
        print(f"    Headers: {sec['headers']}")
        if sec['rows']:
            print(f"    First row ({len(sec['rows'][0])} cells): {sec['rows'][0][:6]}...")
    return sections


def extract_positions(sections):
    sec = sections.get('positions')
    if not sec:
        print("  WARNING: No Positions section found!")
        return []
    headers = [h.lower() for h in sec['headers']]
    positions = []
    for vals in sec['rows']:
        if len(vals) < 5:
            continue
        d = {}
        for i, h in enumerate(headers):
            if i < len(vals):
                d[h] = vals[i]
        hidden_comment = vals[len(headers)] if len(vals) > len(headers) else ''
        pos_id = d.get('position', '')
        if not pos_id or not pos_id.strip() or pos_id.lower() == 'total':
            continue
        positions.append({
            'open_time':   d.get('time', ''),
            'position_id': pos_id,
            'symbol':      d.get('symbol', ''),
            'type':        d.get('type', ''),
            'volume':      d.get('volume', ''),
            'commission':  parse_currency(d.get('commission', '')),
            'swap':        parse_currency(d.get('swap', '')),
            'profit':      parse_currency(d.get('profit', '')),
            'account_ref': hidden_comment,
        })
    for p in positions:
        p['net'] = round(p['profit'] + p['swap'] + p['commission'], 2)
    return positions


def extract_deals(sections):
    sec = sections.get('deals')
    if not sec:
        print("  WARNING: No Deals section found!")
        return []
    headers = [h.lower() for h in sec['headers']]
    deals = []
    for vals in sec['rows']:
        if len(vals) < 5:
            continue
        d = {}
        for i, h in enumerate(headers):
            if i < len(vals):
                d[h] = vals[i]
        deal_id = d.get('deal', '')
        if not deal_id or not deal_id.strip():
            continue
        deals.append({
            'time':       d.get('time', ''),
            'deal_id':    deal_id,
            'symbol':     d.get('symbol', ''),
            'type':       d.get('type', ''),
            'direction':  d.get('direction', ''),
            'profit':     parse_currency(d.get('profit', '')),
            'commission': parse_currency(d.get('commission', '')),
            'swap':       parse_currency(d.get('swap', '')),
            'comment':    d.get('comment', ''),
            'order':      d.get('order', ''),
        })
    return deals


def extract_orders(sections):
    sec = sections.get('orders')
    if not sec:
        return {}
    headers = [h.lower() for h in sec['headers']]
    order_comments = {}
    for vals in sec['rows']:
        d = {}
        for i, h in enumerate(headers):
            if i < len(vals):
                d[h] = vals[i]
        order_id = d.get('order', '')
        comment = d.get('comment', '')
        if order_id and comment:
            order_comments[order_id] = comment
    return order_comments


# ─── Fetch Google Sheet ───────────────────────────────────────
def fetch_sheet_csv(sheet_id, gid=0):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return list(csv.reader(io.StringIO(resp.text)))


def parse_sheet_evaluations(rows):
    header_idx = None
    for i, row in enumerate(rows):
        for cell in row:
            cl = str(cell).lower()
            if 'prop firm' in cl or ('account' in cl and 'size' in cl):
                header_idx = i
                break
        if header_idx is not None:
            break
    if header_idx is None:
        print("  ERROR: No header row found!")
        return [], {}

    headers = [str(h).strip() for h in rows[header_idx]]
    col_map = {h.lower().strip(): i for i, h in enumerate(headers) if h.strip()}
    print(f"  Header row {header_idx}: {headers[:15]}...")

    evaluations = []
    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) <= 1 or not any(str(c).strip() for c in row[:3]):
            continue
        entry = {'_sheet_row': row_idx + 1}
        for col_name, col_idx in col_map.items():
            if col_idx < len(row):
                entry[col_name] = str(row[col_idx]).strip()
        evaluations.append(entry)
    return evaluations, col_map


# ─── Main ─────────────────────────────────────────────────────
def main():
    html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3066167.html'
    sheet_id  = '18lcf74au4ez7pdPhGz4qyRdLoELMGeNEzgysJgGrg2U'

    # STEP 1 — Parse MT5 Report
    print("=" * 80)
    print("  STEP 1: PARSE MT5 HISTORY REPORT (3066167 / Robert Madsen)")
    print("=" * 80)
    sections = parse_mt5_report(html_path)

    positions = extract_positions(sections)
    deals = extract_deals(sections)
    order_comments = extract_orders(sections)
    print(f"\n  Positions extracted: {len(positions)}")
    print(f"  Deals extracted:     {len(deals)}")
    print(f"  Order comments:      {len(order_comments)}")

    balance_ops = [d for d in deals if d['type'] == 'balance']
    total_deposits = sum(d['profit'] for d in balance_ops if d['profit'] > 0)
    total_withdrawals = sum(d['profit'] for d in balance_ops if d['profit'] < 0)
    print(f"\n  Balance ops: {len(balance_ops)}  (deposits ${total_deposits:,.2f}, withdrawals ${total_withdrawals:,.2f})")

    deal_order_comment = {}
    for d in deals:
        if d['comment'] and d['order']:
            deal_order_comment[d['order']] = d['comment']
    deal_order_comment.update(order_comments)

    for p in positions:
        if not p['account_ref']:
            p['account_ref'] = deal_order_comment.get(p['position_id'], '')

    acct_pnl = defaultdict(lambda: {'net': 0.0, 'count': 0, 'positions': []})
    for p in positions:
        key = p['account_ref'] or 'UNKNOWN'
        acct_pnl[key]['net'] += p['net']
        acct_pnl[key]['count'] += 1
        acct_pnl[key]['positions'].append(p)

    print(f"\n  Unique account refs: {len(acct_pnl)}")

    daily_pnl = defaultdict(lambda: {'net': 0.0, 'count': 0})
    for p in positions:
        try:
            dt = datetime.strptime(p['open_time'][:10], '%Y.%m.%d')
            day = dt.strftime('%Y-%m-%d')
        except ValueError:
            day = 'unknown'
        daily_pnl[day]['net'] += p['net']
        daily_pnl[day]['count'] += 1

    print(f"\n  {'Date':<14} {'Trades':>6} {'Net P&L':>14}")
    print("  " + "-" * 38)
    grand_total = 0.0
    for day in sorted(daily_pnl):
        dp = daily_pnl[day]
        print(f"  {day:<14} {dp['count']:>6} {dp['net']:>14.2f}")
        grand_total += dp['net']
    print("  " + "-" * 38)
    print(f"  {'TOTAL':<14} {len(positions):>6} {grand_total:>14.2f}")

    # STEP 2 — Fetch Google Sheet
    print(f"\n{'='*80}")
    print("  STEP 2: FETCH GOOGLE SHEET")
    print("=" * 80)
    sheet_rows = fetch_sheet_csv(sheet_id, gid=0)
    print(f"  Rows fetched (gid=0): {len(sheet_rows)}")
    if sheet_rows:
        print(f"  First row: {sheet_rows[0][:8]}")

    evals, col_map = parse_sheet_evaluations(sheet_rows)
    print(f"  Evaluations parsed: {len(evals)}")
    print(f"  All columns: {list(col_map.keys())}")

    hedge_result_cols = sorted(k for k in col_map if 'hedge result' in k or 'hedgeresult' in k.replace(' ',''))
    hedge_net_cols    = sorted(k for k in col_map if k in ('hedge net', 'hedge net result'))
    farming_net_cols  = sorted(k for k in col_map if 'farming' in k and 'net' in k)

    print(f"\n  Hedge result cols: {hedge_result_cols}")
    print(f"  Hedge net cols:    {hedge_net_cols}")
    print(f"  Farming net cols:  {farming_net_cols}")

    if not hedge_result_cols:
        print("\n  WARNING: No 'hedge result' columns found. All columns:")
        for k, v in sorted(col_map.items(), key=lambda x: x[1]):
            print(f"    Col {v}: '{k}'")
        print("\n  First 3 evaluations:")
        for ev in evals[:3]:
            print(f"    {dict((k,v) for k,v in ev.items() if v and k != '_sheet_row')}")

    # STEP 3 — Extract sheet values
    print(f"\n{'='*80}")
    print("  STEP 3: SHEET HEDGE & FARMING VALUES")
    print("=" * 80)

    sheet_entries = []
    for ev in evals:
        prop = ev.get('prop firm', ev.get('firm', ''))
        size = ev.get('account size', ev.get('size', ''))
        sr = ev['_sheet_row']
        for col in hedge_result_cols:
            raw = ev.get(col, '').strip()
            if not raw or raw.lower() in ('', '$0.00', '0', '$0'):
                continue
            num = parse_sheet_currency(raw)
            if num is not None:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'hedge'})
            elif raw.upper() == 'FARMING':
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': None, 'type': 'farming_marker'})
        for col in hedge_net_cols:
            raw = ev.get(col, '').strip()
            num = parse_sheet_currency(raw)
            if num is not None and num != 0:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'hedge_net'})
        for col in farming_net_cols:
            raw = ev.get(col, '').strip()
            num = parse_sheet_currency(raw)
            if num is not None and num != 0:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'farming_net'})

    hedge_vals = [e for e in sheet_entries if e['type'] == 'hedge']
    hnet_vals = [e for e in sheet_entries if e['type'] == 'hedge_net']
    fnet_vals = [e for e in sheet_entries if e['type'] == 'farming_net']

    print(f"  Individual hedge result values: {len(hedge_vals)}")
    print(f"  Hedge net values:               {len(hnet_vals)}")
    print(f"  Farming net values:             {len(fnet_vals)}")

    sheet_hedge_total = sum(e['value'] for e in hedge_vals)
    sheet_hnet_total = sum(e['value'] for e in hnet_vals)
    sheet_farming_total = sum(e['value'] for e in fnet_vals)

    print(f"\n  Sheet hedge results total:  ${sheet_hedge_total:>12,.2f}")
    print(f"  Sheet hedge net total:      ${sheet_hnet_total:>12,.2f}")
    print(f"  Sheet farming net total:    ${sheet_farming_total:>12,.2f}")
    print(f"  MT5 positions net total:    ${grand_total:>12,.2f}")

    print(f"\n  All sheet hedge entries:")
    for e in hedge_vals:
        print(f"    Row {e['row']:>4} {e['prop'][:25]:<25} {e['col']:<18} {e['raw']:>12} => ${e['value']:>10,.2f}")

    # STEP 4 — MT5 per-account
    print(f"\n{'='*80}")
    print("  STEP 4: MT5 PER-ACCOUNT P&L")
    print("=" * 80)
    print(f"\n  {'Account Ref':<35} {'Trades':>6} {'Net P&L':>14}")
    print("  " + "-" * 58)
    total_acct = 0.0
    for acc in sorted(acct_pnl, key=lambda a: acct_pnl[a]['net']):
        ap = acct_pnl[acc]
        print(f"  {acc[:35]:<35} {ap['count']:>6} {ap['net']:>14.2f}")
        total_acct += ap['net']
    print("  " + "-" * 58)
    print(f"  {'TOTAL':<35} {len(positions):>6} {total_acct:>14.2f}")

    # STEP 5 — Match
    print(f"\n{'='*80}")
    print("  STEP 5: VALUE-MATCHING (Sheet hedge results <-> MT5 account totals)")
    print("=" * 80)

    mt5_vals = [(acc, round(acct_pnl[acc]['net'], 2)) for acc in acct_pnl]
    sheet_nums = [(i, e) for i, e in enumerate(hedge_vals)]

    used_mt5 = set()
    used_sheet = set()
    matches = []

    # Pass 1: exact match within $0.50
    for si, (idx, se) in enumerate(sheet_nums):
        for mi, (acc, mval) in enumerate(mt5_vals):
            if mi in used_mt5:
                continue
            if abs(se['value'] - mval) < 0.50:
                matches.append((se, acc, mval, 'exact'))
                used_mt5.add(mi)
                used_sheet.add(si)
                break

    # Pass 2: sign-flipped
    for si, (idx, se) in enumerate(sheet_nums):
        if si in used_sheet:
            continue
        for mi, (acc, mval) in enumerate(mt5_vals):
            if mi in used_mt5:
                continue
            if abs(se['value'] + mval) < 0.50:
                matches.append((se, acc, mval, 'sign-flipped'))
                used_mt5.add(mi)
                used_sheet.add(si)
                break

    # Pass 3: close match within $5
    for si, (idx, se) in enumerate(sheet_nums):
        if si in used_sheet:
            continue
        best = None
        best_diff = 999999
        for mi, (acc, mval) in enumerate(mt5_vals):
            if mi in used_mt5:
                continue
            diff = abs(se['value'] - mval)
            if diff < 5.0 and diff < best_diff:
                best = (mi, acc, mval)
                best_diff = diff
        if best:
            mi, acc, mval = best
            matches.append((se, acc, mval, f'close(${best_diff:.2f})'))
            used_mt5.add(mi)
            used_sheet.add(si)

    exact_ct = sum(1 for m in matches if m[3] == 'exact')
    flip_ct = sum(1 for m in matches if m[3] == 'sign-flipped')
    close_ct = sum(1 for m in matches if m[3].startswith('close'))
    print(f"\n  Same-sign matches:      {exact_ct}")
    print(f"  Sign-flipped matches:   {flip_ct}")
    print(f"  Close matches:          {close_ct}")
    print(f"  Total matched:          {len(matches)}")

    print(f"\n  {'Row':>4} {'Prop Firm':<22} {'Column':<18} {'Sheet':>10} {'Match':>8} {'MT5 Account':<30} {'MT5 Val':>10}")
    print("  " + "-" * 110)
    for se, acc, mval, mtype in matches:
        flag = '==' if mtype == 'exact' else ('+/-' if mtype == 'sign-flipped' else '~')
        print(f"  {se['row']:>4} {se['prop'][:22]:<22} {se['col']:<18} {se['value']:>10.2f} {flag:>8} {acc[:30]:<30} {mval:>10.2f}")

    unmatched_sheet = [sheet_nums[si] for si in range(len(sheet_nums)) if si not in used_sheet]
    unmatched_mt5 = [mt5_vals[mi] for mi in range(len(mt5_vals)) if mi not in used_mt5]

    if unmatched_sheet:
        print(f"\n  SHEET entries with NO MT5 match ({len(unmatched_sheet)}):")
        for _, se in unmatched_sheet:
            print(f"    Row {se['row']:>4} {se['prop'][:25]:<25} {se['col']:<18} ${se['value']:>10,.2f}  ({se['raw']})")

    if unmatched_mt5:
        print(f"\n  MT5 accounts with NO sheet match ({len(unmatched_mt5)}):")
        for acc, mval in sorted(unmatched_mt5, key=lambda x: x[1]):
            print(f"    {acc[:40]:<40} ${mval:>10,.2f}  ({acct_pnl[acc]['count']} trades)")

    # FINAL SUMMARY
    print(f"\n{'='*80}")
    print("  FINAL SUMMARY")
    print("=" * 80)
    print(f"  MT5 positions net total:      ${grand_total:>14,.2f}")
    print(f"  Sheet hedge results total:    ${sheet_hedge_total:>14,.2f}")
    diff = grand_total - sheet_hedge_total
    print(f"  DIFFERENCE (MT5 - Sheet):     ${diff:>14,.2f}")
    print()
    print(f"  Matched:                      {len(matches)}")
    print(f"  Unmatched sheet entries:       {len(unmatched_sheet)}")
    print(f"  Unmatched MT5 accounts:        {len(unmatched_mt5)}")
    if unmatched_mt5:
        unmatched_total = sum(v for _, v in unmatched_mt5)
        print(f"  Unmatched MT5 net total:      ${unmatched_total:>14,.2f}")
    if unmatched_sheet:
        unmatched_sheet_total = sum(se['value'] for _, se in unmatched_sheet)
        print(f"  Unmatched sheet total:        ${unmatched_sheet_total:>14,.2f}")


if __name__ == '__main__':
    main()
