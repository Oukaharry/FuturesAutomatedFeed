"""
COMPREHENSIVE MT5 <-> SHEET MATCHING: Account 3066167 / Robert Madsen

For EVERY MT5 account ref, matches to:
  - Funded Hedge Results 1-7 (cols 20-26)
  - Funded Hedge Days (cols 38,40,42,...) for farming trades
  - Eval Hedge Results 1-5 (cols 9-13) matched to eval account refs
  
For no-phase accounts: individual MT5 trades matched to sheet hedge days.
For phased accounts (_FD1, _FD2, etc.): aggregate matched to hedge result columns.
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
    prefix_upper = prefix.upper()
    # Check prefix match
    if not sheet_upper.startswith(prefix_upper):
        # Also allow e.g. V2- prefix matching
        if not (prefix_upper.startswith('V2-') and 'V2-' in sheet_upper):
            return False
    # Compare trailing digits
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
    print("=" * 140)
    print("  COMPREHENSIVE MT5 <-> SHEET MATCHING: Account 3066167 / Robert Madsen")
    print("  Matches every MT5 trade to sheet hedge results + hedge day (farming) values")
    print("=" * 140)

    print("\n  Parsing MT5 report...")
    with open(html_path, 'r', encoding='utf-16') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    table = soup.find('table')
    rows = table.find_all('tr')

    in_pos = False
    pos_header = []
    all_positions = []

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

        all_positions.append({
            'full_ref': full_ref,
            'time': d.get('time', ''),
            'symbol': d.get('symbol', ''),
            'type': d.get('type', ''),
            'volume': d.get('volume', ''),
            'profit': profit,
            'swap': swap,
            'commission': commission,
            'net': net,
        })

    # Group trades by ref
    trades_by_ref = defaultdict(list)
    for p in all_positions:
        trades_by_ref[p['full_ref'] or 'UNKNOWN'].append(p)

    # Build per-account P&L
    acct_pnl = {}
    for ref, trades in trades_by_ref.items():
        total_net = round(sum(t['net'] for t in trades), 2)
        acct_pnl[ref] = {'net': total_net, 'count': len(trades)}

    print(f"  MT5 positions: {len(all_positions)}")
    print(f"  MT5 unique account refs: {len(acct_pnl)}")
    mt5_total = round(sum(v['net'] for v in acct_pnl.values()), 2)
    print(f"  MT5 total net P&L: ${mt5_total:,.2f}")

    # Identify which refs have phases and which don't
    phased_refs = set()
    nophase_refs = set()
    for ref in acct_pnl:
        _, _, phase = parse_mt5_ref(ref)
        if phase:
            phased_refs.add(ref)
        else:
            nophase_refs.add(ref)
    print(f"  Phased refs: {len(phased_refs)}, No-phase refs: {len(nophase_refs)}")

    # ── Fetch Google Sheet ──
    print(f"\n  Fetching Google Sheet...")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    raw_rows = list(csv.reader(io.StringIO(resp.text)))

    # Header at row index 1
    header_idx = None
    for i, row in enumerate(raw_rows):
        for cell in row:
            if 'prop firm' in str(cell).lower():
                header_idx = i
                break
        if header_idx is not None:
            break

    headers = [str(h).strip() for h in raw_rows[header_idx]]

    # Parse each sheet row with explicit column positions
    sheet_data = []  # list of dicts
    for row_idx in range(header_idx + 1, len(raw_rows)):
        raw = raw_rows[row_idx]
        if len(raw) <= 1 or not any(str(c).strip() for c in raw[:3]):
            continue

        def cell(idx):
            return str(raw[idx]).strip() if idx < len(raw) else ''

        entry = {
            'row': row_idx + 1,
            'prop': cell(0),
            'eval_acct': cell(8),
            'funded_acct': cell(15),
            'eval_hrs': [],      # (col_name, value)
            'funded_hrs': [],    # (col_name, value)
            'hedge_days': [],    # (day_name, value)
            'farming_net': None,
            'funded_hedge_net': None,
            'eval_hedge_net': None,
        }

        # Eval hedge results (cols 9-13)
        for c in range(9, 14):
            v = parse_sheet_currency(cell(c))
            if v is not None:
                entry['eval_hrs'].append((f'eval HR{c - 8}', v))

        # Eval hedge net (col 14)
        v = parse_sheet_currency(cell(14))
        if v is not None:
            entry['eval_hedge_net'] = v

        # Funded hedge results (cols 20-26)
        for c in range(20, 27):
            v = parse_sheet_currency(cell(c))
            if v is not None:
                entry['funded_hrs'].append((f'funded HR{c - 19}', v))

        # Funded hedge net (col 27)
        v = parse_sheet_currency(cell(27))
        if v is not None:
            entry['funded_hedge_net'] = v

        # Farming net (col 36)
        v = parse_sheet_currency(cell(36))
        if v is not None:
            entry['farming_net'] = v

        # Hedge Day values (cols 38, 40, 42, ... up to 104)
        for c in range(38, min(len(raw), 105), 2):
            v = parse_sheet_currency(cell(c))
            if v is not None:
                day_num = (c - 36) // 2
                entry['hedge_days'].append((f'day{day_num}', v))

        sheet_data.append(entry)

    print(f"  Sheet rows: {len(sheet_data)}")

    # Totals
    sheet_funded_hr_total = round(sum(v for e in sheet_data for _, v in e['funded_hrs']), 2)
    sheet_eval_hr_total = round(sum(v for e in sheet_data for _, v in e['eval_hrs']), 2)
    sheet_hday_total = round(sum(v for e in sheet_data for _, v in e['hedge_days']), 2)
    print(f"  Sheet funded hedge result total: ${sheet_funded_hr_total:,.2f}")
    print(f"  Sheet eval hedge result total:   ${sheet_eval_hr_total:,.2f}")
    print(f"  Sheet hedge day total:           ${sheet_hday_total:,.2f}")
    print(f"  Combined sheet total:            ${sheet_funded_hr_total + sheet_hday_total + sheet_eval_hr_total:,.2f}")

    # ── Global MT5 consumption tracking ──
    mt5_consumed = set()

    def find_mt5_refs(sheet_acct):
        """Find all unconsumed MT5 refs matching a sheet account."""
        candidates = []
        for mt5_ref in acct_pnl:
            if mt5_ref in mt5_consumed:
                continue
            if match_sheet_to_mt5(sheet_acct, mt5_ref):
                candidates.append(mt5_ref)
        return candidates

    # ── MATCHING ──
    print(f"\n{'='*140}")
    print("  FULL TRADE-LEVEL MATCHING")
    print("=" * 140)

    all_match_rows = []
    stats = {'exact': 0, 'close': 0, 'flip': 0, 'off': 0, 'unmatched_sheet': 0, 'mt5_extra': 0}

    def classify(sheet_val, mt5_val):
        diff = round(sheet_val - mt5_val, 2)
        abs_diff = abs(diff)
        sum_val = abs(sheet_val + mt5_val)
        if abs_diff < 0.10:
            return "EXACT", diff
        elif sum_val < abs_diff and sum_val < 5.0:
            return "SIGN FLIP", diff
        elif sum_val < abs_diff:
            return f"FLIP~${sum_val:.0f}", diff
        elif abs_diff < 5.0:
            return "CLOSE", diff
        else:
            return "OFF", diff

    def greedy_match(sheet_values, mt5_values):
        """Greedy 1-to-1 match: for each sheet value, find best MT5 match."""
        remaining = list(mt5_values)
        results = []

        for sheet_label, sheet_val in sheet_values:
            if not remaining:
                results.append((sheet_label, sheet_val, None, 0, "UNMATCHED", 0))
                continue

            best_idx = min(range(len(remaining)), key=lambda i: abs(sheet_val - remaining[i][1]))
            mt5_label, mt5_val = remaining.pop(best_idx)
            status, diff = classify(sheet_val, mt5_val)
            results.append((sheet_label, sheet_val, mt5_label, mt5_val, status, diff))

        # Remaining MT5 are extras
        for mt5_label, mt5_val in remaining:
            results.append(None, 0, mt5_label, mt5_val, "MT5 EXTRA", mt5_val)

        return results

    for entry in sheet_data:
        row_num = entry['row']
        prop = entry['prop']
        funded_acct = entry['funded_acct']
        eval_acct = entry['eval_acct']

        # ── Match FUNDED account ──
        if funded_acct:
            funded_mt5_refs = find_mt5_refs(funded_acct)

            # Separate aggregate vs individual-trade refs
            # _FA and _FD0 are farming phases -> expand to individual trades
            INDIVIDUAL_PHASES = ('FA', 'FD0')
            funded_aggregate = [r for r in funded_mt5_refs if parse_mt5_ref(r)[2] and parse_mt5_ref(r)[2] not in INDIVIDUAL_PHASES]
            funded_individual = [r for r in funded_mt5_refs if not parse_mt5_ref(r)[2] or parse_mt5_ref(r)[2] in INDIVIDUAL_PHASES]

            # Build all sheet values for this funded account (hedge results + hedge days)
            sheet_values = []
            for label, val in entry['funded_hrs']:
                sheet_values.append((label, val))
            for label, val in entry['hedge_days']:
                sheet_values.append((label, val))

            # Build all MT5 values
            # For aggregate refs (_FD1, _FD2, _CH1 etc): use aggregate net per ref
            # For individual refs (no-phase, _FA, _FD0): use individual trades
            mt5_values = []
            for ref in funded_aggregate:
                mt5_values.append((ref, acct_pnl[ref]['net']))
            for ref in funded_individual:
                for trade in trades_by_ref[ref]:
                    mt5_values.append((f"{ref}@{trade['time']}", trade['net']))

            has_data = sheet_values or mt5_values
            if has_data:
                print(f"\n  ─── Row {row_num}: {prop} | Funded: {funded_acct} ───")
                print(f"  Sheet: {len(sheet_values)} values (HR={len(entry['funded_hrs'])}, HedgeDays={len(entry['hedge_days'])})")
                print(f"  MT5:   {len(mt5_values)} values (agg_refs={len(funded_aggregate)}, indiv_trades={sum(len(trades_by_ref[r]) for r in funded_individual)})")
                print(f"  {'Sheet Col':<14} {'Sheet$':>12}  {'MT5 Label':<55} {'MT5$':>12} {'Diff':>10} {'Status':>10}")
                print(f"  {'-'*118}")

                remaining = list(mt5_values)
                for sheet_label, sheet_val in sheet_values:
                    if not remaining:
                        print(f"  {sheet_label:<14} {sheet_val:>12.2f}  {'-- no MT5 --':<55} {'':>12} {'':>10} {'UNMATCHED':>10}")
                        stats['unmatched_sheet'] += 1
                        all_match_rows.append({
                            'row': row_num, 'prop': prop, 'acct': funded_acct, 'section': 'funded',
                            'col': sheet_label, 'sheet': sheet_val, 'mt5_ref': '', 'mt5': 0, 'status': 'UNMATCHED'
                        })
                        continue

                    best_idx = min(range(len(remaining)), key=lambda i: abs(sheet_val - remaining[i][1]))
                    mt5_label, mt5_val = remaining.pop(best_idx)
                    status, diff = classify(sheet_val, mt5_val)

                    if 'FLIP' in status:
                        stats['flip'] += 1
                    elif status == 'EXACT':
                        stats['exact'] += 1
                    elif status == 'CLOSE':
                        stats['close'] += 1
                    elif status == 'OFF':
                        stats['off'] += 1
                    elif status == 'UNMATCHED':
                        stats['unmatched_sheet'] += 1

                    print(f"  {sheet_label:<14} {sheet_val:>12.2f}  {mt5_label:<55} {mt5_val:>12.2f} {diff:>10.2f} {status:>10}")
                    all_match_rows.append({
                        'row': row_num, 'prop': prop, 'acct': funded_acct, 'section': 'funded',
                        'col': sheet_label, 'sheet': sheet_val, 'mt5_ref': mt5_label, 'mt5': mt5_val, 'status': status
                    })

                for mt5_label, mt5_val in remaining:
                    print(f"  {'(mt5 extra)':<14} {'':>12}  {mt5_label:<55} {mt5_val:>12.2f} {mt5_val:>10.2f} {'MT5 EXTRA':>10}")
                    stats['mt5_extra'] += 1
                    all_match_rows.append({
                        'row': row_num, 'prop': prop, 'acct': funded_acct, 'section': 'funded',
                        'col': '(mt5 extra)', 'sheet': 0, 'mt5_ref': mt5_label, 'mt5': mt5_val, 'status': 'MT5 EXTRA'
                    })

                # Show totals
                s_total = round(sum(v for _, v in sheet_values), 2)
                m_total = round(sum(v for _, v in mt5_values), 2)
                if abs(s_total - m_total) > 0.10:
                    print(f"  {'TOTALS:':<14} {s_total:>12.2f}  {'':>55} {m_total:>12.2f} {round(s_total - m_total, 2):>10.2f}")

            # Mark consumed
            for ref in funded_mt5_refs:
                mt5_consumed.add(ref)

        # ── Match EVAL account ──
        if eval_acct and eval_acct != funded_acct:
            eval_mt5_refs = find_mt5_refs(eval_acct)

            eval_aggregate = [r for r in eval_mt5_refs if parse_mt5_ref(r)[2] and parse_mt5_ref(r)[2] not in ('FA', 'FD0')]
            eval_individual = [r for r in eval_mt5_refs if not parse_mt5_ref(r)[2] or parse_mt5_ref(r)[2] in ('FA', 'FD0')]

            eval_sheet_values = [(label, val) for label, val in entry['eval_hrs']]

            eval_mt5_values = []
            for ref in eval_aggregate:
                eval_mt5_values.append((ref, acct_pnl[ref]['net']))
            for ref in eval_individual:
                for trade in trades_by_ref[ref]:
                    eval_mt5_values.append((f"{ref}@{trade['time']}", trade['net']))

            has_eval = eval_sheet_values or eval_mt5_values
            if has_eval:
                print(f"\n  ─── Row {row_num}: {prop} | Eval: {eval_acct} ───")
                print(f"  Sheet: {len(eval_sheet_values)} eval values   MT5: {len(eval_mt5_values)} values")
                print(f"  {'Sheet Col':<14} {'Sheet$':>12}  {'MT5 Label':<55} {'MT5$':>12} {'Diff':>10} {'Status':>10}")
                print(f"  {'-'*118}")

                remaining = list(eval_mt5_values)
                for sheet_label, sheet_val in eval_sheet_values:
                    if not remaining:
                        print(f"  {sheet_label:<14} {sheet_val:>12.2f}  {'-- no MT5 --':<55} {'':>12} {'':>10} {'UNMATCHED':>10}")
                        stats['unmatched_sheet'] += 1
                        all_match_rows.append({
                            'row': row_num, 'prop': prop, 'acct': eval_acct, 'section': 'eval',
                            'col': sheet_label, 'sheet': sheet_val, 'mt5_ref': '', 'mt5': 0, 'status': 'UNMATCHED'
                        })
                        continue

                    best_idx = min(range(len(remaining)), key=lambda i: abs(sheet_val - remaining[i][1]))
                    mt5_label, mt5_val = remaining.pop(best_idx)
                    status, diff = classify(sheet_val, mt5_val)

                    if 'FLIP' in status:
                        stats['flip'] += 1
                    elif status == 'EXACT':
                        stats['exact'] += 1
                    elif status == 'CLOSE':
                        stats['close'] += 1
                    elif status == 'OFF':
                        stats['off'] += 1
                    elif status == 'UNMATCHED':
                        stats['unmatched_sheet'] += 1

                    print(f"  {sheet_label:<14} {sheet_val:>12.2f}  {mt5_label:<55} {mt5_val:>12.2f} {diff:>10.2f} {status:>10}")
                    all_match_rows.append({
                        'row': row_num, 'prop': prop, 'acct': eval_acct, 'section': 'eval',
                        'col': sheet_label, 'sheet': sheet_val, 'mt5_ref': mt5_label, 'mt5': mt5_val, 'status': status
                    })

                for mt5_label, mt5_val in remaining:
                    print(f"  {'(mt5 extra)':<14} {'':>12}  {mt5_label:<55} {mt5_val:>12.2f} {mt5_val:>10.2f} {'MT5 EXTRA':>10}")
                    stats['mt5_extra'] += 1
                    all_match_rows.append({
                        'row': row_num, 'prop': prop, 'acct': eval_acct, 'section': 'eval',
                        'col': '(mt5 extra)', 'sheet': 0, 'mt5_ref': mt5_label, 'mt5': mt5_val, 'status': 'MT5 EXTRA'
                    })

            for ref in eval_mt5_refs:
                mt5_consumed.add(ref)

    # ── MT5 ACCOUNTS WITH NO SHEET MATCH ──
    unmatched_mt5 = {k: v for k, v in acct_pnl.items() if k not in mt5_consumed}
    unmatched_mt5_total = round(sum(v['net'] for v in unmatched_mt5.values()), 2)

    print(f"\n{'='*140}")
    print("  MT5 ACCOUNTS WITH NO SHEET MATCH")
    print("=" * 140)
    print(f"  Total unmatched MT5 accounts: {len(unmatched_mt5)}")
    print(f"  Total unmatched MT5 P&L: ${unmatched_mt5_total:,.2f}")

    if unmatched_mt5:
        print(f"\n  {'MT5 Ref':<45} {'Trades':>6} {'Net P&L':>12}")
        print(f"  {'-'*65}")
        for acc in sorted(unmatched_mt5, key=lambda a: unmatched_mt5[a]['net']):
            v = unmatched_mt5[acc]
            print(f"  {acc:<45} {v['count']:>6} {v['net']:>12.2f}")

    # ── SUMMARY ──
    print(f"\n{'='*140}")
    print("  SUMMARY")
    print("=" * 140)

    matched_count = stats['exact'] + stats['close'] + stats['flip'] + stats['off']

    print(f"\n  MT5 total net P&L:             ${mt5_total:>12,.2f}")
    print(f"  Sheet funded HR total:         ${sheet_funded_hr_total:>12,.2f}")
    print(f"  Sheet hedge day total:         ${sheet_hday_total:>12,.2f}")
    print(f"  Sheet eval HR total:           ${sheet_eval_hr_total:>12,.2f}")
    all_sheet = round(sheet_funded_hr_total + sheet_hday_total + sheet_eval_hr_total, 2)
    print(f"  Sheet ALL values combined:     ${all_sheet:>12,.2f}")
    print(f"  Overall difference:            ${mt5_total - all_sheet:>12,.2f}")

    print(f"\n  Matched pairs:  {matched_count}")
    print(f"    Exact:        {stats['exact']}")
    print(f"    Close (<$5):  {stats['close']}")
    print(f"    Sign flips:   {stats['flip']}")
    print(f"    Value off:    {stats['off']}")
    print(f"  Sheet unmatched:  {stats['unmatched_sheet']}")
    print(f"  MT5 extra (in matched accts): {stats['mt5_extra']}")
    print(f"  MT5 accounts no sheet match:  {len(unmatched_mt5)}")

    # ── DETAILED BREAKDOWN BY METRIC ──
    hdr = f"  {'Row':>4} {'Sect':<6} {'Prop':<20} {'Account':<30} {'Col':<14} {'Sheet$':>12} {'MT5 Label':<50} {'MT5$':>12} {'Diff':>10}"
    sep = f"  {'-'*162}"

    def print_section(title, rows_list):
        print(f"\n{'='*140}")
        print(f"  {title} ({len(rows_list)} entries)")
        print("=" * 140)
        print(hdr)
        print(sep)
        for r in rows_list:
            diff = round(r['sheet'] - r['mt5'], 2)
            print(f"  {r['row']:>4} {r.get('section',''):<6} {r['prop'][:20]:<20} {r['acct'][:30]:<30} {r['col']:<14} {r['sheet']:>12.2f} {r['mt5_ref'][:50]:<50} {r['mt5']:>12.2f} {diff:>10.2f}")

    # EXACT
    exact_rows = [r for r in all_match_rows if r['status'] == 'EXACT']
    print_section("EXACT MATCHES", exact_rows)

    # CLOSE
    close_rows = [r for r in all_match_rows if r['status'] == 'CLOSE']
    print_section("CLOSE MATCHES (<$5 diff)", close_rows)

    # SIGN FLIPS
    flip_rows = [r for r in all_match_rows if 'FLIP' in r.get('status', '')]
    print_section("SIGN FLIPS", flip_rows)

    # VALUE OFF
    off_rows = [r for r in all_match_rows if r['status'] == 'OFF']
    off_rows.sort(key=lambda x: -abs(x['sheet'] - x['mt5']))
    print_section("VALUE OFF (>$5 diff)", off_rows)

    # SHEET UNMATCHED
    unmatched_rows = [r for r in all_match_rows if r['status'] == 'UNMATCHED']
    print_section("SHEET VALUES WITH NO MT5 MATCH", unmatched_rows)

    # MT5 EXTRA
    extra_rows = [r for r in all_match_rows if r['status'] == 'MT5 EXTRA']
    print_section("MT5 EXTRA TRADES (no sheet slot)", extra_rows)


if __name__ == '__main__':
    main()
