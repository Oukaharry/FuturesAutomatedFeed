"""Fix prop firm / account number mismatches in Chris's evaluations.
 
Root cause: resolve_account() matched raw numbers (e.g. '2123') to session_accounts 
from ANY firm, so V2-2123 could land on a 'My Funded Futures' row.

Fix: For each row, if Account # or Account #.1 has a prefix that doesn't match 
the Prop Firm, try to re-resolve using the correct firm prefix. If no match exists,
clear the bad account.
"""
import csv, json, re, sqlite3, os

EXTRACTED_JSON = '_chris_ream_extracted.json'
OUTPUT_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
DB_PATH = 'dashboard/dashboard.db'

with open(EXTRACTED_JSON) as f:
    jdata = json.load(f)

session_accts = jdata['session_accounts']
account_maps = jdata['account_maps']

FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU', 'Tradeify': 'TDFY', 'Topstep': 'V2',
    'TradeDay': 'TDF', 'FundedNext': 'FNFT', 'Apex Trader Funding': 'APEX',
    'BluSky': 'BLSKY', 'TheFundedTrader': 'TFT', 'Alpha Futures': 'AFAD',
    'Bulenox': 'BLX', 'FastTrackTrading': 'FTT', 'TickTickTrader': 'TTT',
    'Earn2Trade': 'E2T', 'Maverick Trading': 'MAV', 'Elite Trader Funding': 'ETF',
    'Leeloo Trading': 'LELO', 'Funding Ticks': 'FTKS',
}
PREFIX_TO_FIRM = {v: k for k, v in FIRM_TO_PREFIX.items()}

# Build lookup: partial number -> list of full accounts (there may be multiple prefixes)
partial_to_fulls = {}
for full_acct in session_accts:
    if '-' in full_acct:
        prefix, num = full_acct.split('-', 1)
        if num not in partial_to_fulls:
            partial_to_fulls[num] = []
        partial_to_fulls[num].append(full_acct)

def get_prefix(acct):
    """Get the prefix from an account like FNFT-12345 -> FNFT"""
    if acct and '-' in acct:
        return acct.split('-')[0]
    return None

def expected_prefix_for_firm(firm):
    return FIRM_TO_PREFIX.get(firm)

def resolve_for_firm(partial_num, firm):
    """Try to find a session account matching partial_num with the right firm prefix."""
    exp_prefix = expected_prefix_for_firm(firm)
    if not exp_prefix:
        return None
    # Check session_accounts for prefix-partial_num
    target = f'{exp_prefix}-{partial_num}'
    if target in session_accts or any(sa == target for sa in session_accts):
        return target
    # If not in session, still build the correct one using firm prefix
    return f'{exp_prefix}-{partial_num}'

# Load current DB data
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
print(f'Current evaluations: {len(evals)}')

# Also load fixed CSV to keep in sync
with open(OUTPUT_PATH, 'r', encoding='utf-8-sig') as f:
    csv_rows = list(csv.DictReader(f))
print(f'Fixed CSV rows: {len(csv_rows)}')

fixed_count = 0
cleared_count = 0

for dataset_name, dataset in [('DB', evals), ('CSV', csv_rows)]:
    fixes = 0
    clears = 0
    for i, ev in enumerate(dataset):
        firm = (ev.get('Prop Firm') or '').strip()
        if not firm:
            continue
        exp_prefix = expected_prefix_for_firm(firm)
        
        for field in ('Account #', 'Account #.1'):
            acct = (ev.get(field) or '').strip()
            if not acct:
                continue
            prefix = get_prefix(acct)
            if not prefix:
                continue
            
            # Check if prefix matches the firm
            expected_firm = PREFIX_TO_FIRM.get(prefix)
            if expected_firm and expected_firm != firm:
                # MISMATCH! Account prefix doesn't match Prop Firm
                partial_num = acct.split('-', 1)[1] if '-' in acct else acct
                
                if exp_prefix:
                    # Try to resolve with correct firm prefix
                    correct_acct = f'{exp_prefix}-{partial_num}'
                    # Check if this correct account exists in session_accounts
                    if correct_acct in session_accts:
                        ev[field] = correct_acct
                        fixes += 1
                    else:
                        # The partial number doesn't belong to this firm at all
                        # Check account_maps to see if we have other accounts for this row
                        row_key = str(i)
                        maps = account_maps.get(row_key, [])
                        # Find entries that match this column
                        if field == 'Account #':
                            matching = [e for e in maps if e['phase'].upper().startswith('CH')]
                        else:
                            matching = [e for e in maps if e['phase'].upper() in ('FA', 'FD', 'DD')]
                        
                        replaced = False
                        for entry in matching:
                            candidate_num = entry['account']
                            candidate_full = f'{exp_prefix}-{candidate_num}'
                            if candidate_full in session_accts:
                                ev[field] = candidate_full
                                fixes += 1
                                replaced = True
                                break
                        
                        if not replaced:
                            # Clear the mismatched account - it was placed on wrong row
                            ev[field] = ''
                            clears += 1
    
    print(f'\n{dataset_name}: {fixes} accounts re-resolved, {clears} mismatched accounts cleared')
    if dataset_name == 'DB':
        fixed_count = fixes
        cleared_count = clears

# Save DB
from datetime import datetime
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
            (json.dumps(evals),))
cur.execute("SELECT MAX(version) FROM data_history WHERE client_id='Chris'")
new_ver = (cur.fetchone()[0] or 0) + 1
cur.execute("""INSERT INTO data_history 
    (client_id, version, action, changed_by, changed_by_type, ip_address, change_source, change_description, evaluations, created_at)
    VALUES ('Chris', ?, 'UPDATE', 'system_fix', 'super_admin', '127.0.0.1', 'firm_acct_fix', ?, ?, ?)""",
    (new_ver,
     f'Fixed {fixed_count} mismatched account prefixes, cleared {cleared_count} unresolvable accounts',
     json.dumps(evals),
     datetime.now().isoformat()))
db.commit()
db.close()

# Save CSV
cols = list(csv_rows[0].keys()) if csv_rows else []
with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=cols)
    writer.writeheader()
    writer.writerows(csv_rows)

# Final verification
print(f'\n--- Verification ---')
mismatches_remaining = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    if not firm:
        continue
    for field in ('Account #', 'Account #.1'):
        acct = (ev.get(field) or '').strip()
        if not acct or '-' not in acct:
            continue
        prefix = acct.split('-')[0]
        expected_firm = PREFIX_TO_FIRM.get(prefix)
        if expected_firm and expected_firm != firm:
            mismatches_remaining += 1
            if mismatches_remaining <= 10:
                print(f'  Row {i+1}: Firm="{firm}"  {field}="{acct}" (expected {expected_firm})')

print(f'Remaining mismatches: {mismatches_remaining}')
print('Done.')
