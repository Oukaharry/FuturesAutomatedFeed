"""
FULL MATCH: Every MT5 account ref <-> corresponding sheet hedge result values.
Groups by sheet account number, matches all MT5 phases (FD1, FD2, FA, etc.)
to sheet hedge result columns 1-7 using 1-to-1 greedy assignment.
"""
import re, csv, io
from collections import defaultdict, OrderedDict
from bs4 import BeautifulSoup
import requests


def parse_currency(val):
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


def parse_mt5_ref(ref):
    """Parse MT5 ref like 'FNFT...41745_FD1' into (prefix, suffix, phase)."""
    m = re.match(r'^([A-Z0-9\-]+?)\.\.\.(.+?)(?:_(FD\d|CH\d|FA|DD\d|UNK|FD0))?$', ref)
    if m:
        return m.group(1), m.group(2), m.group(3) or ''
    return ref, '', ''


def match_sheet_to_mt5(sheet_acct, mt5_ref):
    """Check if a sheet account# matches an MT5 ref by prefix + trailing digits."""
    if not sheet_acct or not mt5_ref:
        return False
    prefix, suffix, phase = parse_mt5_ref(mt5_ref)
    if not suffix:
        return False
    sheet_upper = sheet_acct.upper()
    if not sheet_upper.startswith(prefix) and prefix not in sheet_upper:
        if prefix.startswith('V2-') and 'V2-' in sheet_upper:
            pass
        else:
            return False
    sheet_tail = re.search(r'(\d+)$', sheet_acct)
    if not sheet_tail:
        return False
    suffix_digits = re.sub(r'[^0-9]', '', suffix)
    if suffix_digits and sheet_tail.group(1).endswith(suffix_digits):
        return True
    if suffix in sheet_acct:
        return True
    return False


def main():
    html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3066167.html'
    sheet_id  = '18lcf74au4ez7pdPhGz4qyRdLoELMGeNEzgysJgGrg2U'

    # ── Parse MT5 ──
    print("=" * 120)
    print("  FULL MT5 <-> SHEET MATCHING: Account 3066167 / Robert Madsen")
    print("=" * 120)
    print("\n  Parsing MT5 report...")
    with open(html_path, 'r', encoding='utf-16') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    table = soup.find('table')
    rows = table.find_all('tr')

    in_pos = False
    pos_header = []
    positions = []

    for row in rows:
        tds = row.find_all(['td', 'th'])
        if not tds:
            continue
        first = tds[0]
        if first.get('colspan'):
            text = first.get_text(strip=True)
            if text == 'Positions':
                in_pos = True
                continue
            elif text in ('Orders', 'Deals', 'Balance:', 'Credit Facility:'):
                in_pos = False
                continue
        if not in_pos:
            continue

        bold_count = sum(1 for td in tds if td.find('b'))
        if not pos_header and bold_count >= len(tds) // 2 and bold_count >= 3:
            for td in tds:
                if 'hidden' not in td.get('class', []):
                    pos_header.append(td.get_text(strip=True))
            continue

        visible = []
        hidden_val = None
        for td in tds:
            if 'hidden' in td.get('class', []):
                hidden_val = td.get_text(strip=True)
                continue
            visible.append(td.get_text(strip=True))

        if len(visible) < 5:
            continue

        d = {}
        for i, h in enumerate(pos_header):
            if i < len(visible):
                d[h.lower()] = visible[i]

        pos_id = d.get('position', '')
        if not pos_id or pos_id.lower() == 'total':
            continue

        full_ref = hidden_val or ''
        commission = parse_currency(d.get('commission', ''))
        swap = parse_currency(d.get('swap', ''))
        profit = parse_currency(d.get('profit', ''))
        net = round(profit + swap + commission, 2)

        positions.append({
            'full_ref': full_ref,
            'net': net,
        })

    # Build per-account P&L
    acct_pnl = defaultdict(lambda: {'net': 0.0, 'count': 0})
    for p in positions:
        key = p['full_ref'] or 'UNKNOWN'
        acct_pnl[key]['net'] += p['net']
        acct_pnl[key]['count'] += 1
    for k in acct_pnl:
        acct_pnl[k]['net'] = round(acct_pnl[k]['net'], 2)

    print(f"  MT5 positions: {len(positions)}")
    print(f"  MT5 unique account refs: {len(acct_pnl)}")

    mt5_total = round(sum(v['net'] for v in acct_pnl.values()), 2)
    print(f"  MT5 total net P&L: ${mt5_total:,.2f}")

    # ── Fetch Google Sheet ──
    print(f"\n  Fetching Google Sheet...")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    sheet_rows = list(csv.reader(io.StringIO(resp.text)))

    header_idx = None
    for i, row in enumerate(sheet_rows):
        for cell in row:
            if 'prop firm' in str(cell).lower():
                header_idx = i
                break
        if header_idx is not None:
            break

    headers = [str(h).strip() for h in sheet_rows[header_idx]]
    col_map = {h.lower().strip(): i for i, h in enumerate(headers) if h.strip()}
    hr_cols = sorted(k for k in col_map if 'hedge result' in k)

    evals = []
    for row_idx in range(header_idx + 1, len(sheet_rows)):
        row = sheet_rows[row_idx]
        if len(row) <= 1 or not any(str(c).strip() for c in row[:3]):
            continue
        entry = {'_row': row_idx + 1}
        for col_name, col_idx in col_map.items():
            if col_idx < len(row):
                entry[col_name] = str(row[col_idx]).strip()
        evals.append(entry)

    print(f"  Sheet evaluations: {len(evals)}")
    print(f"  Hedge result columns: {hr_cols}")

    # ── Build sheet data: all hedge results per account ──
    # For each sheet account, collect all non-zero hedge result values
    sheet_acct_hr = OrderedDict()  # acct -> [{'row','prop','col','val'}, ...]
    for ev in evals:
        prop = ev.get('prop firm', '')
        sheet_acct = ev.get('account #', ev.get('account number', '')).strip()
        sr = ev['_row']
        if not sheet_acct:
            continue
        if sheet_acct not in sheet_acct_hr:
            sheet_acct_hr[sheet_acct] = {'prop': prop, 'row': sr, 'hrs': []}
        for col in hr_cols:
            raw = ev.get(col, '').strip()
            if not raw:
                continue
            num = parse_sheet_currency(raw)
            if num is not None and num != 0:
                sheet_acct_hr[sheet_acct]['hrs'].append({
                    'col': col, 'val': num, 'raw': raw
                })

    sheet_total = round(sum(
        h['val'] for info in sheet_acct_hr.values() for h in info['hrs']
    ), 2)
    print(f"  Sheet total hedge results: ${sheet_total:,.2f}")
    print(f"  Difference: ${mt5_total - sheet_total:,.2f}")

    # Track which MT5 refs have been globally consumed
    mt5_consumed = set()

    # ── Find MT5 matches for each sheet account ──
    def find_mt5_matches(sheet_acct):
        candidates = []
        for mt5_ref, mt5_data in acct_pnl.items():
            if mt5_ref in mt5_consumed:
                continue
            if match_sheet_to_mt5(sheet_acct, mt5_ref):
                candidates.append((mt5_ref, mt5_data['net'], mt5_data['count']))
        return candidates

    # ── FULL MATCHING TABLE ──
    print(f"\n{'='*120}")
    print("  FULL MATCHING: Every MT5 value <-> Sheet hedge result")
    print("  (Grouped by sheet account #, 1-to-1 greedy assignment by closest value)")
    print("=" * 120)

    total_matched = 0
    total_exact = 0
    total_close = 0
    total_sign_flip = 0
    total_mismatch = 0
    sheet_unmatched_hrs = 0
    all_rows = []  # for summary

    for sheet_acct, info in sheet_acct_hr.items():
        prop = info['prop']
        row_num = info['row']
        hrs = info['hrs']
        candidates = find_mt5_matches(sheet_acct)

        if not candidates and not hrs:
            continue

        # Sort hedge results by column name
        hrs_sorted = sorted(hrs, key=lambda x: x['col'])
        remaining = list(candidates)  # [(ref, net, count), ...]

        print(f"\n  --- Row {row_num}: {prop} | {sheet_acct} ---")
        print(f"  {'Col':<18} {'Sheet$':>12} {'MT5 Ref':<45} {'MT5$':>12} {'Diff':>10} {'Status':>10}")
        print(f"  {'-'*110}")

        acct_sheet_total = 0.0
        acct_mt5_total = 0.0

        for hr in hrs_sorted:
            sheet_val = hr['val']
            acct_sheet_total += sheet_val

            if not remaining:
                print(f"  {hr['col']:<18} {sheet_val:>12.2f} {'-- no MT5 left --':<45} {'':>12} {'':>10} {'UNMATCHED':>10}")
                sheet_unmatched_hrs += 1
                all_rows.append({
                    'row': row_num, 'prop': prop, 'acct': sheet_acct,
                    'col': hr['col'], 'sheet': sheet_val, 'mt5_ref': '',
                    'mt5': 0, 'diff': sheet_val, 'status': 'UNMATCHED'
                })
                continue

            # Find best match from remaining MT5 entries
            best_idx = -1
            best_diff = 999999
            for idx, (ref, net, cnt) in enumerate(remaining):
                diff_same = abs(sheet_val - net)
                diff_flip = abs(sheet_val + net)
                min_diff = min(diff_same, diff_flip)
                if min_diff < best_diff:
                    best_diff = min_diff
                    best_idx = idx

            ref, net, cnt = remaining.pop(best_idx)
            mt5_consumed.add(ref)
            acct_mt5_total += net

            diff = round(sheet_val - net, 2)
            abs_diff = abs(diff)

            if abs_diff < 0.05:
                status = "EXACT"
                total_exact += 1
            elif abs(sheet_val + net) < 0.05:
                status = "SIGN FLIP"
                total_sign_flip += 1
            elif abs(sheet_val + net) < abs_diff:
                status = f"FLIP~${abs(sheet_val + net):.2f}"
                total_sign_flip += 1
            elif abs_diff < 5.0:
                status = "CLOSE"
                total_close += 1
            else:
                status = f"OFF"
                total_mismatch += 1

            total_matched += 1
            print(f"  {hr['col']:<18} {sheet_val:>12.2f} {ref:<45} {net:>12.2f} {diff:>10.2f} {status:>10}")
            all_rows.append({
                'row': row_num, 'prop': prop, 'acct': sheet_acct,
                'col': hr['col'], 'sheet': sheet_val, 'mt5_ref': ref,
                'mt5': net, 'diff': diff, 'status': status
            })

        # Show any remaining (unmatched) MT5 entries for this account
        for ref, net, cnt in remaining:
            mt5_consumed.add(ref)
            acct_mt5_total += net
            print(f"  {'(no sheet col)':<18} {'':>12} {ref:<45} {net:>12.2f} {net:>10.2f} {'MT5 EXTRA':>10}")
            all_rows.append({
                'row': row_num, 'prop': prop, 'acct': sheet_acct,
                'col': '(mt5 extra)', 'sheet': 0, 'mt5_ref': ref,
                'mt5': net, 'diff': -net, 'status': 'MT5 EXTRA'
            })

        acct_diff = round(acct_sheet_total - acct_mt5_total, 2)
        if abs(acct_diff) > 0.05:
            print(f"  {'ACCOUNT TOTALS:':<18} {acct_sheet_total:>12.2f} {'':>45} {acct_mt5_total:>12.2f} {acct_diff:>10.2f}")

    # ── MT5 accounts with NO sheet match at all ──
    unmatched_mt5 = {k: v for k, v in acct_pnl.items() if k not in mt5_consumed}
    unmatched_mt5_total = round(sum(v['net'] for v in unmatched_mt5.values()), 2)

    print(f"\n{'='*120}")
    print("  MT5 ACCOUNTS WITH NO SHEET MATCH")
    print("=" * 120)
    print(f"  Total unmatched MT5 accounts: {len(unmatched_mt5)}")
    print(f"  Total unmatched MT5 P&L: ${unmatched_mt5_total:,.2f}")

    if unmatched_mt5:
        print(f"\n  {'MT5 Ref':<45} {'Trades':>6} {'Net P&L':>12}")
        print(f"  {'-'*65}")
        for acc in sorted(unmatched_mt5, key=lambda a: unmatched_mt5[a]['net']):
            v = unmatched_mt5[acc]
            print(f"  {acc:<45} {v['count']:>6} {v['net']:>12.2f}")

    # ── SUMMARY ──
    print(f"\n{'='*120}")
    print("  SUMMARY")
    print("=" * 120)

    matched_sheet_total = round(sum(r['sheet'] for r in all_rows if r['status'] not in ('MT5 EXTRA',)), 2)
    matched_mt5_total = round(sum(r['mt5'] for r in all_rows), 2)
    mt5_extra_total = round(sum(r['mt5'] for r in all_rows if r['status'] == 'MT5 EXTRA'), 2)

    print(f"\n  MT5 total net P&L:           ${mt5_total:>12,.2f}")
    print(f"  Sheet total hedge results:   ${sheet_total:>12,.2f}")
    print(f"  Overall difference:          ${mt5_total - sheet_total:>12,.2f}")

    print(f"\n  Matched pairs:  {total_matched}")
    print(f"    Exact:        {total_exact}")
    print(f"    Close (<$5):  {total_close}")
    print(f"    Sign flips:   {total_sign_flip}")
    print(f"    Value off:    {total_mismatch}")

    print(f"\n  Sheet hedge results with no MT5 match: {sheet_unmatched_hrs}")
    print(f"  MT5 extra entries (no sheet column):    {sum(1 for r in all_rows if r['status'] == 'MT5 EXTRA')}")
    print(f"  MT5 accounts with no sheet match:       {len(unmatched_mt5)}")

    print(f"\n  Matched sheet total:    ${matched_sheet_total:>12,.2f}")
    print(f"  Matched MT5 total:      ${matched_mt5_total:>12,.2f}")
    print(f"  MT5 extra (in-acct):    ${mt5_extra_total:>12,.2f}")
    print(f"  MT5 no-match total:     ${unmatched_mt5_total:>12,.2f}")

    # ── SIGN FLIP DETAIL ──
    flips = [r for r in all_rows if 'FLIP' in r['status']]
    if flips:
        print(f"\n{'='*120}")
        print("  SIGN FLIP DETAILS")
        print("=" * 120)
        print(f"  {'Row':>4} {'Prop':<20} {'Account #':<30} {'Col':<18} {'Sheet$':>12} {'MT5 Ref':<45} {'MT5$':>12}")
        print(f"  {'-'*145}")
        for f in flips:
            print(f"  {f['row']:>4} {f['prop'][:20]:<20} {f['acct'][:30]:<30} {f['col']:<18} {f['sheet']:>12.2f} {f['mt5_ref']:<45} {f['mt5']:>12.2f}")
    else:
        print(f"\n  No sign flips found.")

    # ── VALUE MISMATCHES > $50 ──
    off_rows = [r for r in all_rows if r['status'] == 'OFF' and abs(r['diff']) > 50]
    if off_rows:
        print(f"\n{'='*120}")
        print(f"  VALUE MISMATCHES > $50 ({len(off_rows)} entries)")
        print("=" * 120)
        print(f"  {'Row':>4} {'Prop':<20} {'Account #':<30} {'Col':<18} {'Sheet$':>12} {'MT5 Ref':<45} {'MT5$':>12} {'Diff':>10}")
        print(f"  {'-'*155}")
        for r in sorted(off_rows, key=lambda x: -abs(x['diff'])):
            print(f"  {r['row']:>4} {r['prop'][:20]:<20} {r['acct'][:30]:<30} {r['col']:<18} {r['sheet']:>12.2f} {r['mt5_ref']:<45} {r['mt5']:>12.2f} {r['diff']:>10.2f}")


if __name__ == '__main__':
    main()
