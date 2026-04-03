#!/usr/bin/env python3
"""Debug: show exactly what data the JSON report has for repair."""
import json, os, sqlite3

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

report = json.load(open(REPORT_PATH))
conn = sqlite3.connect(DB_PATH)

# Pick a few clients with known empty rows
test_clients = ['Chris Ream']

for cid in test_clients:
    print(f"\n{'='*80}")
    print(f"CLIENT: {cid}")
    print(f"{'='*80}")

    cd = report.get('clients', {}).get(cid)
    if not cd:
        print("  NOT IN JSON REPORT")
        continue

    # Session accounts
    sa = cd.get('session_accounts', [])
    print(f"\n  session_accounts: {len(sa)} total")

    # Eval account map
    eam = cd.get('eval_account_map', {})
    print(f"  eval_account_map: {len(eam)} entries")

    # Build suffix map
    suffix_to_full = {}
    for full_acct in sa:
        if '-' in full_acct:
            suffix = full_acct.rsplit('-', 1)[1]
            suffix_to_full.setdefault(suffix, full_acct)

    # Build row->acct map
    row_to_acct = {}
    for row_str, acct in eam.items():
        if isinstance(acct, dict):
            row_to_acct[int(row_str)] = str(acct.get('account', ''))
        else:
            row_to_acct[int(row_str)] = str(acct)

    PREFIX_TO_FIRM = {
        'FNFT': 'FundedNext', 'MFFU': 'My Funded Futures',
        'TDF': 'TradeDay', 'TDFY': 'Tradeify', 'FTDFY': 'Tradeify',
        'AFAD': 'Alpha Futures', 'V2': 'Topstep', '50KTC': 'Topstep',
        'ELTD': 'TradeDay', 'TDFUNDED': 'TradeDay',
    }

    # DB state
    row = conn.execute(
        'SELECT evaluations FROM clients_data WHERE client_id = ?', (cid,)
    ).fetchone()
    if not row:
        print("  NOT IN DB")
        continue

    evals = json.loads(row[0] or '[]')
    print(f"  DB eval rows: {len(evals)}")

    # Categorize all rows
    has_both = 0
    has_acct_no_firm = 0
    has_firm_no_acct = 0
    has_neither = 0
    fixable_acct = 0
    fixable_firm = 0
    unfixable = 0

    problem_rows = []
    for idx, ev in enumerate(evals):
        acct = ev.get('Account Number', '').strip()
        firm = ev.get('Prop Firm', '').strip()

        if acct and firm:
            has_both += 1
            continue

        if acct and not firm:
            has_acct_no_firm += 1
        elif firm and not acct:
            has_firm_no_acct += 1
        else:
            has_neither += 1

        # Can we fix this?
        partial = row_to_acct.get(idx, '')
        if not partial and acct:
            partial = acct.rsplit('-', 1)[-1] if '-' in acct else acct

        full = suffix_to_full.get(partial, '') if partial else ''
        derived_firm = ''
        if full and '-' in full:
            prefix = full.rsplit('-', 1)[0].upper()
            derived_firm = PREFIX_TO_FIRM.get(prefix, '')

        # Heuristic fallback
        if not derived_firm and partial:
            if len(partial) <= 4 and partial.isdigit():
                derived_firm = 'Topstep'
            elif partial and partial[0].isalpha():
                derived_firm = 'FundedNext'

        can_fix_acct = bool(not acct and partial)
        can_fix_firm = bool(not firm and derived_firm)
        in_eval_map = idx in row_to_acct
        in_suffix = bool(full)

        if can_fix_acct or can_fix_firm:
            if can_fix_acct:
                fixable_acct += 1
            if can_fix_firm:
                fixable_firm += 1
        elif not acct or not firm:
            unfixable += 1
            if len(problem_rows) < 200:
                problem_rows.append({
                    'idx': idx, 'acct': acct, 'firm': firm,
                    'partial': partial, 'in_eval_map': in_eval_map,
                    'in_suffix': in_suffix, 'full': full,
                    'derived_firm': derived_firm,
                })

    print(f"\n  SUMMARY:")
    print(f"    Complete (acct + firm): {has_both}")
    print(f"    Has acct, no firm:     {has_acct_no_firm}")
    print(f"    Has firm, no acct:     {has_firm_no_acct}")
    print(f"    Neither:               {has_neither}")
    print(f"    Fixable (acct):        {fixable_acct}")
    print(f"    Fixable (firm):        {fixable_firm}")
    print(f"    Unfixable:             {unfixable}")

    if problem_rows:
        print(f"\n  ROWS STILL MISSING PROP FIRM (first 50):")
        no_firm = [pr for pr in problem_rows if not pr['firm']]
        no_acct = [pr for pr in problem_rows if not pr['acct']]
        has_acct_no_firm = [pr for pr in problem_rows if pr['acct'] and not pr['firm']]
        has_firm_no_acct = [pr for pr in problem_rows if pr['firm'] and not pr['acct']]
        neither = [pr for pr in problem_rows if not pr['firm'] and not pr['acct']]

        if has_acct_no_firm:
            print(f"\n    --- Has Account but NO Firm ({len(has_acct_no_firm)}) ---")
            for pr in has_acct_no_firm[:50]:
                print(f"    Row {pr['idx']:>4}: Acct='{pr['acct']}'")

        if has_firm_no_acct:
            print(f"\n    --- Has Firm but NO Account ({len(has_firm_no_acct)}) ---")
            for pr in has_firm_no_acct[:50]:
                print(f"    Row {pr['idx']:>4}: Firm='{pr['firm']}'")

        if neither:
            print(f"\n    --- No Firm AND No Account ({len(neither)}) ---")
            for pr in neither[:20]:
                print(f"    Row {pr['idx']:>4}: (completely empty)")

        # Show all rows with raw data for manual checking
        print(f"\n  ALL INCOMPLETE ROWS (DB index → Display #):")
        print(f"  {'DB idx':>6} {'Display#':>8} {'Account':>15} {'Firm':<25} {'HR1':>10}")
        print(f"  {'─'*6} {'─'*8} {'─'*15} {'─'*25} {'─'*10}")
        total_rows = len(evals)
        for idx, ev in enumerate(evals):
            acct = ev.get('Account Number', '').strip()
            firm = ev.get('Prop Firm', '').strip()
            hr1 = ev.get('Hedge Result 1', '')
            if acct and firm:
                continue
            display_num = total_rows - idx
            print(f"  {idx:>6} {display_num:>8} {acct:>15} {firm:<25} {str(hr1):>10}")

conn.close()
print("\nDone.")
