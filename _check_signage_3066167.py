"""
Focused analysis: hedge results > $1000 with signage check.
Match by FULL account number (first+last digits) from sheet 'Account #' column
to MT5 position account refs.
"""
import re, csv, io
from collections import defaultdict
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


def main():
    html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3066167.html'
    sheet_id  = '18lcf74au4ez7pdPhGz4qyRdLoELMGeNEzgysJgGrg2U'

    # ── Parse MT5 ──
    print("=" * 90)
    print("  PARSING MT5 REPORT")
    print("=" * 90)
    with open(html_path, 'r', encoding='utf-16') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    table = soup.find('table')
    rows = table.find_all('tr')

    # Extract positions with FULL account refs
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

        # Header row
        bold_count = sum(1 for td in tds if td.find('b'))
        if not pos_header and bold_count >= len(tds) // 2 and bold_count >= 3:
            for td in tds:
                cls = td.get('class', [])
                if 'hidden' in cls:
                    continue
                pos_header.append(td.get_text(strip=True))
            continue

        # Data row - get visible + hidden
        visible = []
        hidden_val = None
        for td in tds:
            cls = td.get('class', [])
            if 'hidden' in cls:
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
            'position_id': pos_id,
            'symbol': d.get('symbol', ''),
            'type': d.get('type', ''),
            'profit': profit,
            'commission': commission,
            'swap': swap,
            'net': net,
            'full_ref': full_ref,
        })

    print(f"  Positions: {len(positions)}")

    # Show some full refs to understand format
    refs = set(p['full_ref'] for p in positions if p['full_ref'])
    print(f"  Unique full account refs: {len(refs)}")
    print(f"\n  Sample full refs (first 15):")
    for r in sorted(refs)[:15]:
        print(f"    '{r}'")

    # Build per-account P&L using FULL ref
    acct_pnl = defaultdict(lambda: {'net': 0.0, 'count': 0})
    for p in positions:
        key = p['full_ref'] or 'UNKNOWN'
        acct_pnl[key]['net'] += p['net']
        acct_pnl[key]['count'] += 1

    # Round
    for k in acct_pnl:
        acct_pnl[k]['net'] = round(acct_pnl[k]['net'], 2)

    # Filter MT5 accounts with |net| > 1000
    big_mt5 = {k: v for k, v in acct_pnl.items() if abs(v['net']) > 1000}
    print(f"\n  MT5 accounts with |net| > $1000: {len(big_mt5)}")
    print(f"  {'Full Account Ref':<45} {'Trades':>6} {'Net P&L':>12}")
    print("  " + "-" * 65)
    for acc in sorted(big_mt5, key=lambda a: big_mt5[a]['net']):
        ap = big_mt5[acc]
        print(f"  {acc:<45} {ap['count']:>6} {ap['net']:>12.2f}")

    # ── Fetch Google Sheet ──
    print(f"\n{'='*90}")
    print("  FETCHING GOOGLE SHEET")
    print("=" * 90)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    sheet_rows = list(csv.reader(io.StringIO(resp.text)))

    # Find header
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

    # Find hedge result columns & account # column
    hr_cols = sorted(k for k in col_map if 'hedge result' in k)
    acct_col = col_map.get('account #', col_map.get('account number', None))
    hn_col = col_map.get('hedge net', None)

    print(f"  Hedge result cols: {hr_cols}")
    print(f"  Account # column index: {acct_col}")
    print(f"  Hedge net column index: {hn_col}")

    # Parse evaluations
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

    print(f"  Evaluations: {len(evals)}")

    # Extract hedge results > $1000 (absolute)
    print(f"\n{'='*90}")
    print("  SHEET HEDGE RESULTS WITH |value| > $1000")
    print("=" * 90)

    big_sheet = []
    for ev in evals:
        prop = ev.get('prop firm', '')
        acct_num = ev.get('account #', ev.get('account number', ''))
        sr = ev['_row']
        for col in hr_cols:
            raw = ev.get(col, '').strip()
            if not raw:
                continue
            num = parse_sheet_currency(raw)
            if num is not None and abs(num) > 1000:
                big_sheet.append({
                    'row': sr, 'prop': prop, 'acct': acct_num,
                    'col': col, 'raw': raw, 'value': num
                })

    print(f"  Found {len(big_sheet)} hedge results with |value| > $1000\n")
    print(f"  {'Row':>4} {'Prop Firm':<22} {'Account #':<20} {'Column':<18} {'Value':>12}")
    print("  " + "-" * 80)
    for e in big_sheet:
        print(f"  {e['row']:>4} {e['prop'][:22]:<22} {e['acct'][:20]:<20} {e['col']:<18} {e['value']:>12.2f}")

    # ── PRECISE MATCHING by account number ──
    print(f"\n{'='*90}")
    print("  PRECISE MATCHING: Sheet Account # <-> MT5 Full Ref")
    print("=" * 90)

    # Show what account numbers look like in the sheet
    all_acct_nums = set()
    for ev in evals:
        a = ev.get('account #', ev.get('account number', '')).strip()
        if a:
            all_acct_nums.add(a)
    print(f"\n  Unique sheet account numbers: {len(all_acct_nums)}")
    print(f"  Sample sheet account #s (first 15):")
    for a in sorted(all_acct_nums)[:15]:
        print(f"    '{a}'")

    # Build lookup: for each sheet account#, find matching MT5 ref
    # The MT5 refs look like "MFFU-90012" or "FNFT-17980_FD1" etc.
    # The sheet account# might be the number portion
    # Let's see what patterns exist

    def parse_mt5_ref(ref):
        """Parse MT5 ref like 'FNFT...41745_FD1' into (prefix, suffix, phase)."""
        m = re.match(r'^([A-Z0-9\-]+?)\.\.\.(.+?)(?:_(FD\d|CH\d|FA|DD\d|UNK))?$', ref)
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
        # Sheet acct must start with something matching the MT5 prefix
        # MT5: "MFFU" -> sheet "MFFUSFFLX..." or "MFFUSFSCL..."
        # MT5: "V2-"  -> sheet "EXPRESS-V2-486522-..."
        # MT5: "FTDF" -> sheet "FTDFYSLX..."
        # MT5: "FNFT" -> sheet "FNFTFA..."
        # MT5: "FTPR" -> sheet "FTPROPLUSM..."
        # MT5: "TDFY" -> sheet "TDFY..."
        sheet_upper = sheet_acct.upper()
        if not sheet_upper.startswith(prefix) and prefix not in sheet_upper:
            # Special case: V2- prefix maps to EXPRESS-V2-
            if prefix.startswith('V2-') and 'V2-' in sheet_upper:
                pass
            else:
                return False
        # Check trailing digits: the MT5 suffix must appear at the end of sheet's digits
        sheet_tail = re.search(r'(\d+)$', sheet_acct)
        if not sheet_tail:
            return False
        # The suffix from MT5 (e.g. "41745", "90155", "6798") must be at end of sheet trailing digits
        # or suffix contains non-digit chars (e.g. "N9142")
        suffix_digits = re.sub(r'[^0-9]', '', suffix)
        if suffix_digits and sheet_tail.group(1).endswith(suffix_digits):
            return True
        # Also check if suffix with letters matches (e.g. N9142)
        if suffix in sheet_acct:
            return True
        return False

    def find_mt5_matches(sheet_acct):
        """Find all MT5 accounts matching this sheet account#."""
        candidates = []
        for mt5_ref, mt5_data in acct_pnl.items():
            if match_sheet_to_mt5(sheet_acct, mt5_ref):
                candidates.append((mt5_ref, mt5_data['net']))
        return candidates

    # Group big sheet entries by account number so we can match all hedge results together
    from collections import OrderedDict
    acct_groups = OrderedDict()
    for e in big_sheet:
        key = e['acct'].strip()
        if key not in acct_groups:
            acct_groups[key] = []
        acct_groups[key].append(e)

    print(f"\n  MATCHING BIG HEDGE RESULTS TO MT5 ACCOUNTS:")
    print(f"  (When multiple MT5 entries exist for an account, each hedge result is matched 1-to-1)")
    print(f"  {'Row':>4} {'Prop':<18} {'Sheet Acct#':<28} {'Col':<16} {'Sheet$':>10} {'MT5 Ref':<45} {'MT5$':>10} {'Sign':>8}")
    print("  " + "-" * 150)

    for acct_key, entries in acct_groups.items():
        candidates = find_mt5_matches(acct_key)

        if not candidates:
            for e in entries:
                print(f"  {e['row']:>4} {e['prop'][:18]:<18} {acct_key[:28]:<28} {e['col']:<16} {e['value']:>10.2f} {'NO MATCH':<45} {'':>10} {'???':>8}")
            continue

        # Sort hedge results by column name (hedge result 1, 2, 3...)
        entries_sorted = sorted(entries, key=lambda x: x['col'])

        # Greedy 1-to-1 assignment: for each hedge result, find best MT5 match
        # from remaining unassigned MT5 entries
        remaining = list(candidates)  # [(ref, net), ...]
        for e in entries_sorted:
            sheet_val = e['value']
            if not remaining:
                print(f"  {e['row']:>4} {e['prop'][:18]:<18} {acct_key[:28]:<28} {e['col']:<16} {sheet_val:>10.2f} {'(all MT5 used up)':<45} {'':>10} {'???':>8}")
                continue

            best = None
            best_diff = 999999
            best_idx = -1
            for idx, (ref, net) in enumerate(remaining):
                diff_same = abs(sheet_val - net)
                diff_flip = abs(sheet_val + net)
                min_diff = min(diff_same, diff_flip)
                if min_diff < best_diff:
                    best_diff = min_diff
                    best = (ref, net)
                    best_idx = idx

            if best:
                ref, net = best
                # Remove this MT5 entry so it's not reused for another hedge result
                remaining.pop(best_idx)
                diff_same = abs(sheet_val - net)
                diff_flip = abs(sheet_val + net)
                if diff_same <= diff_flip:
                    sign_status = "OK" if diff_same < 1.0 else f"~${diff_same:.2f}"
                else:
                    sign_status = "FLIP!" if diff_flip < 5.0 else f"FLIP~${diff_flip:.2f}"
                print(f"  {e['row']:>4} {e['prop'][:18]:<18} {acct_key[:28]:<28} {e['col']:<16} {sheet_val:>10.2f} {ref:<45} {net:>10.2f} {sign_status:>8}")

    # ── Check ALL hedge results for sign issues ──
    print(f"\n{'='*90}")
    print("  ALL HEDGE RESULTS: SIGNAGE CHECK (matched by account #)")
    print("=" * 90)

    sign_issues = []
    matched_count = 0
    unmatched_count = 0

    # Group all evals by account number
    acct_eval_groups = OrderedDict()
    for ev in evals:
        sheet_acct = ev.get('account #', ev.get('account number', '')).strip()
        if not sheet_acct:
            continue
        if sheet_acct not in acct_eval_groups:
            acct_eval_groups[sheet_acct] = []
        acct_eval_groups[sheet_acct].append(ev)

    for sheet_acct, ev_list in acct_eval_groups.items():
        # Collect all hedge result values for this account
        hr_entries = []
        for ev in ev_list:
            prop = ev.get('prop firm', '')
            sr = ev['_row']
            for col in hr_cols:
                raw = ev.get(col, '').strip()
                if not raw:
                    continue
                num = parse_sheet_currency(raw)
                if num is None or num == 0:
                    continue
                hr_entries.append({'row': sr, 'prop': prop, 'col': col, 'val': num})

        if not hr_entries:
            continue

        # Find all MT5 matches for this account
        candidates = find_mt5_matches(sheet_acct)
        if not candidates:
            unmatched_count += len(hr_entries)
            continue

        # Sort hedge results by column name for consistent ordering
        hr_entries.sort(key=lambda x: (x['row'], x['col']))

        # Greedy 1-to-1 assignment
        remaining = list(candidates)
        for hr in hr_entries:
            num = hr['val']
            if not remaining:
                # No more MT5 entries, but still have hedge results
                unmatched_count += 1
                continue

            best = None
            best_diff = 999999
            best_idx = -1
            for idx, (ref, net) in enumerate(remaining):
                diff_same = abs(num - net)
                diff_flip = abs(num + net)
                min_diff = min(diff_same, diff_flip)
                if min_diff < best_diff:
                    best_diff = min_diff
                    best = (ref, net, diff_same, diff_flip)
                    best_idx = idx

            if best:
                ref, net, diff_same, diff_flip = best
                remaining.pop(best_idx)
                matched_count += 1
                is_flip = diff_flip < diff_same
                if is_flip and diff_flip < 5.0:
                    sign_issues.append({
                        'row': hr['row'], 'prop': hr['prop'], 'acct': sheet_acct,
                        'col': hr['col'], 'sheet_val': num, 'mt5_ref': ref,
                        'mt5_val': net, 'diff': diff_flip
                    })

    print(f"\n  Matched: {matched_count}, Unmatched: {unmatched_count}")
    print(f"  SIGN FLIPS FOUND: {len(sign_issues)}")

    if sign_issues:
        print(f"\n  {'Row':>4} {'Prop':<18} {'Sheet Acct#':<20} {'Col':<16} {'Sheet$':>10} {'MT5 Ref':<45} {'MT5$':>10} {'Diff':>8}")
        print("  " + "-" * 140)
        for si in sign_issues:
            print(f"  {si['row']:>4} {si['prop'][:18]:<18} {si['acct'][:20]:<20} {si['col']:<16} {si['sheet_val']:>10.2f} {si['mt5_ref']:<45} {si['mt5_val']:>10.2f} {si['diff']:>8.2f}")

    # Total impact
    if sign_issues:
        total_sheet = sum(si['sheet_val'] for si in sign_issues)
        total_mt5 = sum(si['mt5_val'] for si in sign_issues)
        print(f"\n  Total sheet (sign-flipped entries): ${total_sheet:,.2f}")
        print(f"  Total MT5   (sign-flipped entries): ${total_mt5:,.2f}")
        print(f"  Sign-flip impact on difference:     ${total_sheet - total_mt5:,.2f}")
        print(f"  (If corrected, would change diff by ${2*total_sheet:,.2f})")


if __name__ == '__main__':
    main()
