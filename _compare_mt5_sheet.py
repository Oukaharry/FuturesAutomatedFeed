"""
Compare MT5 History Report (HTML) vs Google Sheet to find missing/mismatched entries.
The MT5 report has a SINGLE table with section headers (Positions, Orders, Deals).
Each section has its own column layout. We parse all sections correctly.
"""
import re, csv, io
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
    s = re.sub(r'-\s+', '-', s)  # "- 131" → "-131"
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
    if s.lower() in ('pass', 'farming', 'n/a', '-', ''):
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


# ─── 1. Parse MT5 HTML (single table with section headers) ────
def parse_mt5_report(html_path):
    """Parse the single-table MT5 HTML history report into sections."""
    with open(html_path, 'r', encoding='utf-16') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    table = soup.find('table')
    rows = table.find_all('tr')
    print(f"Total <tr> rows in table: {len(rows)}")

    sections = {}          # { 'positions': { 'headers': [...], 'rows': [[...], ...] }, ... }
    current_section = None
    current_headers = []
    section_rows = []

    for row in rows:
        # ── Section header? e.g. <th ...><b>Deals</b></th>
        ths = row.find_all('th')
        if ths:
            for th in ths:
                b = th.find('b')
                if b:
                    name = b.get_text(strip=True)
                    if name in ('Positions', 'Orders', 'Deals'):
                        # save previous
                        if current_section and section_rows:
                            sections[current_section] = {'headers': current_headers, 'rows': section_rows}
                        current_section = name.lower()
                        current_headers = []
                        section_rows = []
            continue

        tds = row.find_all('td')
        if not tds or current_section is None:
            continue

        # ── Column header row?  (bgcolor="#E5F0FC" and bold cells)
        if row.get('bgcolor', '').upper() == '#E5F0FC' or row.get('align') == 'center':
            bold_count = sum(1 for td in tds if td.find('b'))
            if bold_count >= len(tds) // 2:
                current_headers = []
                for td in tds:
                    if 'hidden' in (td.get('class') or []):
                        continue
                    current_headers.append(td.get_text(strip=True))
                continue

        # ── Data row: skip hidden <td>, read visible ones
        visible_vals = []
        hidden_val = None
        for td in tds:
            if 'hidden' in (td.get('class') or []):
                hidden_val = td.get_text(strip=True)
                continue
            visible_vals.append(td.get_text(strip=True))

        if hidden_val is not None:
            visible_vals.append(hidden_val)          # store as extra "_hidden" field
        section_rows.append(visible_vals)

    # save last section
    if current_section and section_rows:
        sections[current_section] = {'headers': current_headers, 'rows': section_rows}

    for name, sec in sections.items():
        print(f"  Section '{name}': {len(sec['headers'])} headers, {len(sec['rows'])} data rows")
        print(f"    Headers: {sec['headers']}")
        if sec['rows']:
            print(f"    First row ({len(sec['rows'][0])} cells): {sec['rows'][0][:6]}...")
    return sections


# ─── 2. Extract Deals ─────────────────────────────────────────
def extract_deals(sections):
    sec = sections.get('deals')
    if not sec:
        print("  ⚠ No Deals section found!")
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
        # hidden comment stored as extra element
        if len(vals) > len(headers):
            d['_hidden'] = vals[len(headers)]
        # skip summary / totals
        deal_id = d.get('deal', '')
        if not deal_id or not deal_id.strip() or deal_id.lower() == 'total':
            continue
        deals.append({
            'time':       d.get('time', ''),
            'deal_id':    deal_id,
            'symbol':     d.get('symbol', ''),
            'type':       d.get('type', ''),
            'direction':  d.get('direction', ''),
            'volume':     d.get('volume', ''),
            'price':      d.get('price', ''),
            'order':      d.get('order', ''),
            'commission': parse_currency(d.get('commission', '')),
            'fee':        parse_currency(d.get('fee', '')),
            'swap':       parse_currency(d.get('swap', '')),
            'profit':     parse_currency(d.get('profit', '')),
            'balance':    parse_currency(d.get('balance', '')),
            'comment':    d.get('comment', ''),
        })
    return deals


# ─── 3. Extract Positions (completed trades) ──────────────────
def extract_positions(sections):
    sec = sections.get('positions')
    if not sec:
        print("  ⚠ No Positions section found!")
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
        # Hidden field = account identifier (e.g. "FNFT...17408")
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


# ─── 4. Extract Orders (for comment → order mapping) ──────────
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


# ─── 5. Fetch Google Sheet ────────────────────────────────────
def fetch_sheet_csv(sheet_id, gid=0):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return list(csv.reader(io.StringIO(resp.text)))


def parse_sheet_evaluations(rows):
    header_idx = None
    for i, row in enumerate(rows):
        for cell in row:
            if 'prop firm' in str(cell).lower():
                header_idx = i
                break
        if header_idx is not None:
            break
    if header_idx is None:
        print("  ⚠ Could not find header row!")
        return [], {}

    headers = [str(h).strip() for h in rows[header_idx]]
    col_map = {h.lower().strip(): i for i, h in enumerate(headers) if h.strip()}

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


# ─── 6. Main ──────────────────────────────────────────────────
def main():
    html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3081193.html'
    sheet_id  = '13SypBWLmyCT7FK_KLJnCOkGZ4rtbezpaGUXDaQJnQY0'

    # ════════════════════════════════════════════════════════════
    #  STEP 1 — Parse MT5 Report
    # ════════════════════════════════════════════════════════════
    print("=" * 80)
    print("  STEP 1: PARSE MT5 HISTORY REPORT")
    print("=" * 80)
    sections = parse_mt5_report(html_path)

    deals     = extract_deals(sections)
    positions = extract_positions(sections)
    order_comments = extract_orders(sections)
    print(f"\n  Deals extracted:     {len(deals)}")
    print(f"  Positions extracted: {len(positions)}")
    print(f"  Order comments:      {len(order_comments)}")

    # Categorise deals
    balance_ops    = [d for d in deals if d['type'] == 'balance']
    trade_deals_in = [d for d in deals if d['direction'] == 'in' and d['symbol']]
    trade_deals_out= [d for d in deals if d['direction'] == 'out' and d['symbol']]

    total_deposits    = sum(d['profit'] for d in balance_ops if d['profit'] > 0)
    total_withdrawals = sum(d['profit'] for d in balance_ops if d['profit'] < 0)
    print(f"\n  Balance ops: {len(balance_ops)}  (deposits ${total_deposits:,.2f}, withdrawals ${total_withdrawals:,.2f})")
    print(f"  Trade entries (in):  {len(trade_deals_in)}")
    print(f"  Trade exits  (out): {len(trade_deals_out)}")

    # Build order → comment lookup from Deals comment field + Orders section
    deal_order_comment = {}
    for d in deals:
        if d['comment'] and d['order']:
            deal_order_comment[d['order']] = d['comment']
    deal_order_comment.update(order_comments)

    # Attach account ref to positions from deals/orders comments
    for p in positions:
        if not p['account_ref']:
            p['account_ref'] = deal_order_comment.get(p['position_id'], '')

    # ── Per-account P&L from positions ──
    acct_pnl = defaultdict(lambda: {'net': 0.0, 'count': 0, 'positions': []})
    for p in positions:
        key = p['account_ref'] or 'UNKNOWN'
        acct_pnl[key]['net'] += p['net']
        acct_pnl[key]['count'] += 1
        acct_pnl[key]['positions'].append(p)

    print(f"\n  Unique account refs: {len(acct_pnl)}")

    # ── Daily P&L summary ──
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

    # ════════════════════════════════════════════════════════════
    #  STEP 2 — Fetch Google Sheet
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  STEP 2: FETCH GOOGLE SHEET")
    print("=" * 80)
    rows = fetch_sheet_csv(sheet_id)
    evals, col_map = parse_sheet_evaluations(rows)
    print(f"  Rows fetched: {len(rows)},  Evaluations: {len(evals)}")

    hedge_result_cols = sorted(k for k in col_map if 'hedge result' in k)
    hedge_net_cols    = sorted(k for k in col_map if k == 'hedge net')
    farming_net_cols  = sorted(k for k in col_map if 'farming' in k and 'net' in k)
    hedge_day_cols    = sorted(k for k in col_map if 'hedge day' in k)
    print(f"  Hedge result cols: {hedge_result_cols}")
    print(f"  Hedge net cols:    {hedge_net_cols}")
    print(f"  Farming net cols:  {farming_net_cols}")
    print(f"  Hedge day cols:    {len(hedge_day_cols)}")

    # ════════════════════════════════════════════════════════════
    #  STEP 3 — Extract sheet hedge & farming values
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  STEP 3: SHEET HEDGE & FARMING VALUES")
    print("=" * 80)

    sheet_entries = []  # individual hedge result values
    for ev in evals:
        prop  = ev.get('prop firm', '')
        size  = ev.get('account size', '')
        sr    = ev['_sheet_row']
        # Hedge result columns
        for col in hedge_result_cols:
            raw = ev.get(col, '').strip()
            if not raw or raw.lower() in ('', '$0.00', '0'):
                continue
            num = parse_sheet_currency(raw)
            if num is not None:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'hedge'})
            elif raw.upper() == 'FARMING':
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': None, 'type': 'farming_marker'})
        # Hedge net
        for col in hedge_net_cols:
            raw = ev.get(col, '').strip()
            num = parse_sheet_currency(raw)
            if num is not None and num != 0:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'hedge_net'})
        # Farming net
        for col in farming_net_cols:
            raw = ev.get(col, '').strip()
            num = parse_sheet_currency(raw)
            if num is not None and num != 0:
                sheet_entries.append({'row': sr, 'prop': prop, 'size': size,
                                      'col': col, 'raw': raw, 'value': num, 'type': 'farming_net'})

    hedge_vals  = [e for e in sheet_entries if e['type'] == 'hedge']
    hnet_vals   = [e for e in sheet_entries if e['type'] == 'hedge_net']
    fnet_vals   = [e for e in sheet_entries if e['type'] == 'farming_net']

    print(f"  Individual hedge result values: {len(hedge_vals)}")
    print(f"  Hedge net values:               {len(hnet_vals)}")
    print(f"  Farming net values:             {len(fnet_vals)}")

    sheet_hedge_total   = sum(e['value'] for e in hedge_vals)
    sheet_hnet_total    = sum(e['value'] for e in hnet_vals)
    sheet_farming_total = sum(e['value'] for e in fnet_vals)

    print(f"\n  Sheet hedge results total:  ${sheet_hedge_total:>12,.2f}")
    print(f"  Sheet hedge net total:      ${sheet_hnet_total:>12,.2f}")
    print(f"  Sheet farming net total:    ${sheet_farming_total:>12,.2f}")
    print(f"  MT5 positions net total:    ${grand_total:>12,.2f}")

    # ════════════════════════════════════════════════════════════
    #  STEP 4 — Account-level comparison
    # ════════════════════════════════════════════════════════════
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

    # ════════════════════════════════════════════════════════════
    #  STEP 5 -- Match hedge results <-> MT5 account P&L
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  STEP 5: VALUE-MATCHING  (Sheet hedge results <-> MT5 account totals)")
    print("=" * 80)

    mt5_vals = [(acc, round(acct_pnl[acc]['net'], 2)) for acc in acct_pnl]
    sheet_nums = [(i, e) for i, e in enumerate(hedge_vals)]

    used_mt5 = set()
    used_sheet = set()
    matches = []

    # Pass 1: exact match within $0.50 (same sign)
    for si, (idx, se) in enumerate(sheet_nums):
        for mi, (acc, mval) in enumerate(mt5_vals):
            if mi in used_mt5:
                continue
            if abs(se['value'] - mval) < 0.50:
                matches.append((se, acc, mval, 'exact'))
                used_mt5.add(mi)
                used_sheet.add(si)
                break

    # Pass 2: sign-flipped match (sheet = -MT5, within $0.50)
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

    exact_ct = sum(1 for m in matches if m[3] == 'exact')
    flip_ct  = sum(1 for m in matches if m[3] == 'sign-flipped')
    print(f"\n  Same-sign matches:      {exact_ct}")
    print(f"  Sign-flipped matches:   {flip_ct}")
    print(f"  Total matched:          {len(matches)}")

    print(f"\n  {'Row':>4} {'Prop Firm':<22} {'Column':<16} {'Sheet':>10} {'Match':>6} {'MT5 Account':<30} {'MT5 Val':>10}")
    print("  " + "-" * 105)
    for se, acc, mval, mtype in matches:
        flag = '==' if mtype == 'exact' else '+/-'
        print(f"  {se['row']:>4} {se['prop'][:22]:<22} {se['col']:<16} {se['value']:>10.2f} {flag:>6} {acc:<30} {mval:>10.2f}")

    unmatched_sheet = [sheet_nums[si] for si in range(len(sheet_nums)) if si not in used_sheet]
    unmatched_mt5   = [mt5_vals[mi] for mi in range(len(mt5_vals)) if mi not in used_mt5]

    if unmatched_sheet:
        print(f"\n  SHEET hedge results with NO MT5 match ({len(unmatched_sheet)}):")
        for _, se in unmatched_sheet:
            print(f"    Row {se['row']:>4} {se['prop'][:25]:<25} {se['col']:<18} ${se['value']:>10.2f}  ({se['raw']})")

    # ════════════════════════════════════════════════════════════
    #  STEP 6 -- Categorise unmatched MT5 accounts
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  STEP 6: UNMATCHED MT5 ACCOUNTS -- CATEGORISED")
    print("=" * 80)

    # Parse suffix to categorise: _FD1=Funded1, _CH1=Challenge1, _FA=Farming, etc.
    import re as _re
    suffix_re = _re.compile(r'_([A-Z]+\d*)$')
    categories = defaultdict(list)
    for acc, mval in unmatched_mt5:
        m = suffix_re.search(acc)
        suffix = m.group(1) if m else 'BASE'
        categories[suffix].append((acc, mval))

    cat_order = ['FD1','FD2','FD3','FD4','CH1','CH2','CH3','FA','DD2','UNK','BASE']
    cat_labels = {
        'FD1': 'Funded Phase 1', 'FD2': 'Funded Phase 2', 'FD3': 'Funded Phase 3',
        'FD4': 'Funded Phase 4', 'CH1': 'Challenge 1', 'CH2': 'Challenge 2',
        'CH3': 'Challenge 3', 'FA': 'Farming', 'DD2': 'DD Phase 2',
        'UNK': 'Unknown Phase', 'BASE': 'No Suffix (initial)',
    }

    for cat in cat_order:
        if cat not in categories:
            continue
        items = categories[cat]
        total = sum(v for _, v in items)
        label = cat_labels.get(cat, cat)
        print(f"\n  [{cat}] {label}  --  {len(items)} accounts, total ${total:,.2f}")
        print(f"  {'Account':<35} {'Net P&L':>12} {'Trades':>6}")
        print("  " + "-" * 58)
        for acc, mval in sorted(items, key=lambda x: x[1]):
            print(f"  {acc:<35} {mval:>12.2f} {acct_pnl[acc]['count']:>6}")

    # Any remaining categories not in our predefined order
    for cat in sorted(categories):
        if cat in cat_order:
            continue
        items = categories[cat]
        total = sum(v for _, v in items)
        print(f"\n  [{cat}] Other  --  {len(items)} accounts, total ${total:,.2f}")
        for acc, mval in sorted(items, key=lambda x: x[1]):
            print(f"    {acc:<35} {mval:>12.2f} {acct_pnl[acc]['count']:>6}")

    # ════════════════════════════════════════════════════════════
    #  STEP 7 -- Base-account grouping (strip suffix, sum phases)
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  STEP 7: GROUPED BY BASE ACCOUNT (all phases combined)")
    print("=" * 80)

    base_re = _re.compile(r'^(.+?)(?:_(?:FD\d|CH\d|FA|DD\d|UNK))?$')
    base_groups = defaultdict(lambda: {'total': 0.0, 'count': 0, 'phases': []})
    for acc, mval in unmatched_mt5:
        bm = base_re.match(acc)
        base = bm.group(1) if bm else acc
        base_groups[base]['total'] += mval
        base_groups[base]['count'] += acct_pnl[acc]['count']
        base_groups[base]['phases'].append((acc, mval))

    print(f"\n  {len(base_groups)} unique base accounts NOT in sheet")
    print(f"\n  {'Base Account':<25} {'Phases':>6} {'Trades':>6} {'Total Net':>14}")
    print("  " + "-" * 58)
    grand_unmatched = 0.0
    for base in sorted(base_groups, key=lambda b: base_groups[b]['total']):
        bg = base_groups[base]
        print(f"  {base[:25]:<25} {len(bg['phases']):>6} {bg['count']:>6} {bg['total']:>14.2f}")
        grand_unmatched += bg['total']
    print("  " + "-" * 58)
    print(f"  {'TOTAL UNMATCHED':<25} {'':>6} {'':>6} {grand_unmatched:>14.2f}")

    # ════════════════════════════════════════════════════════════
    #  SUMMARY
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  FINAL SUMMARY")
    print("=" * 80)
    print(f"  MT5 positions net total:      ${grand_total:>14,.2f}")
    print(f"  Sheet hedge results total:    ${sheet_hedge_total:>14,.2f}")
    diff = grand_total - sheet_hedge_total
    print(f"  DIFFERENCE (MT5 - Sheet):     ${diff:>14,.2f}")
    print()
    print(f"  Matched (same sign):          {exact_ct}")
    print(f"  Matched (sign-flipped):       {flip_ct}")
    print(f"  Unmatched sheet entries:      {len(unmatched_sheet)}")
    print(f"  Unmatched MT5 accounts:       {len(unmatched_mt5)}")
    print(f"  Unmatched MT5 base accounts:  {len(base_groups)}")
    print(f"  Unmatched MT5 net total:      ${grand_unmatched:>14,.2f}")

    if abs(grand_unmatched) > 1.0:
        print(f"\n  WARNING: ${abs(grand_unmatched):,.2f} of MT5 P&L has no matching sheet entry!")


if __name__ == '__main__':
    main()
