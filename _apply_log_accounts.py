"""
Apply log-extracted account fixes to Chris's evaluations.
CRITICAL: Only apply accounts whose prefix matches the row's Prop Firm.
"""
import json, re, sqlite3, csv
from collections import defaultdict

DB_PATH = 'dashboard/dashboard.db'
OUTPUT_CSV = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU', 'Tradeify': 'TDFY', 'Topstep': 'V2',
    'TradeDay': 'TDF', 'FundedNext': 'FNFT', 'Apex Trader Funding': 'APEX',
    'BluSky': 'BLSKY', 'TheFundedTrader': 'TFT', 'Alpha Futures': 'AFAD',
    'Bulenox': 'BLX', 'FastTrackTrading': 'FTT', 'TickTickTrader': 'TTT',
    'Earn2Trade': 'E2T', 'Maverick Trading': 'MAV', 'Elite Trader Funding': 'ETF',
    'Leeloo Trading': 'LELO', 'Funding Ticks': 'FTKS',
}
PREFIX_TO_FIRM = {v: k for k, v in FIRM_TO_PREFIX.items()}

CORRUPTED_PATTERNS = [
    re.compile(r'^MFFU-?MFFU(EVSTP|EVSCL|SFSCL|EVCRFLX|EVFLX)\d+$'),
    re.compile(r'^MFFU(EVSTP|EVSCL|SFSCL|EVCRFLX|EVFLX)\d+$'),
    re.compile(r'^FNFT-?FNFTCH\w+$'),
    re.compile(r'^TDFY-?TDFYSL\d+$'),
    re.compile(r'^50KTC-V2-\d+-\d+$'),
    re.compile(r'^FTPROPLUS\d+$'),
    re.compile(r'^AFAD-?AFADVEV\d+$'),
]

def is_corrupted(val):
    if not val: return False
    val = val.strip()
    for p in CORRUPTED_PATTERNS:
        if p.match(val): return True
    return False

def get_prefix(acct):
    if acct and '-' in acct:
        return acct.split('-')[0]
    return None

# Load log extraction data
with open('_log_account_fixes.json', 'r') as f:
    log_data = json.load(f)

row_to_accounts = log_data['row_to_accounts']  # str(row) -> [(full_acct, phase), ...]

# Load DB data
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Evaluations: {len(evals)}')

# First pass: clear corrupted accounts
cleared_count = 0
for i, ev in enumerate(evals):
    for field in ('Account #', 'Account #.1'):
        val = (ev.get(field) or '').strip()
        if is_corrupted(val):
            ev[field] = ''
            cleared_count += 1

print(f'Cleared corrupted accounts: {cleared_count}')

# Second pass: apply log accounts with FIRM PREFIX FILTERING
applied_a = 0
applied_a1 = 0
skipped_mismatch = 0
no_match = 0

for row_str, acct_phase_list in row_to_accounts.items():
    row_idx = int(row_str)
    if row_idx >= len(evals):
        continue
    
    ev = evals[row_idx]
    firm = (ev.get('Prop Firm') or '').strip()
    exp_prefix = FIRM_TO_PREFIX.get(firm, '')
    
    curr_a = (ev.get('Account #') or '').strip()
    curr_a1 = (ev.get('Account #.1') or '').strip()
    
    # Group by phase
    ch_accounts = []  # for Account #
    fa_accounts = []  # for Account #.1
    
    for full_acct, phase in acct_phase_list:
        if phase.upper().startswith('CH'):
            ch_accounts.append(full_acct)
        elif phase.upper() in ('FA', 'FD', 'DD'):
            fa_accounts.append(full_acct)
    
    # Apply Account # if needed
    if not curr_a:
        # ONLY accept accounts matching the firm prefix
        matching = [a for a in ch_accounts if get_prefix(a) == exp_prefix]
        if matching:
            ev['Account #'] = matching[0]
            applied_a += 1
        elif ch_accounts and not exp_prefix:
            ev['Account #'] = ch_accounts[0]
            applied_a += 1
        elif ch_accounts:
            skipped_mismatch += 1
    
    # Apply Account #.1 if needed
    if not curr_a1:
        matching = [a for a in fa_accounts if get_prefix(a) == exp_prefix]
        if matching:
            ev['Account #.1'] = matching[0]
            applied_a1 += 1
        elif fa_accounts and not exp_prefix:
            ev['Account #.1'] = fa_accounts[0]
            applied_a1 += 1
        elif fa_accounts:
            skipped_mismatch += 1

print(f'\nApplied Account #: {applied_a}')
print(f'Applied Account #.1: {applied_a1}')
print(f'Skipped (prefix mismatch): {skipped_mismatch}')

# Third pass: for rows where log had wrong-prefix accounts,
# check if ANY entry across all pushes had the right prefix
# Also try: if the account_maps from the original extraction has correct ones
with open('_chris_ream_extracted.json', 'r') as f:
    jdata = json.load(f)
    
am = jdata['account_maps']  # str(row) -> [{account, phase, num}]
session_accts = set(jdata['session_accounts'])

extra_applied = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    exp_prefix = FIRM_TO_PREFIX.get(firm, '')
    if not exp_prefix:
        continue
    
    for field, phase_filter in [('Account #', lambda p: p.upper().startswith('CH')),
                                 ('Account #.1', lambda p: p.upper() in ('FA', 'FD', 'DD'))]:
        val = (ev.get(field) or '').strip()
        if val:
            continue
        
        # Check account_maps
        row_key = str(i)
        maps = am.get(row_key, [])
        for entry in maps:
            if phase_filter(entry['phase']):
                partial = entry['account']
                candidate = f'{exp_prefix}-{partial}'
                if candidate in session_accts:
                    ev[field] = candidate
                    extra_applied += 1
                    break

print(f'Extra from account_maps (firm-filtered): {extra_applied}')

# Final statistics
has_a = sum(1 for ev in evals if (ev.get('Account #') or '').strip())
has_a1 = sum(1 for ev in evals if (ev.get('Account #.1') or '').strip())
has_either = sum(1 for ev in evals 
                 if (ev.get('Account #') or '').strip() or (ev.get('Account #.1') or '').strip())
miss_both = len(evals) - has_either

# Check remaining mismatches
remaining_mismatch = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    exp_prefix = FIRM_TO_PREFIX.get(firm)
    if not exp_prefix:
        continue
    for field in ('Account #', 'Account #.1'):
        val = (ev.get(field) or '').strip()
        if val and '-' in val:
            prefix = val.split('-')[0]
            if PREFIX_TO_FIRM.get(prefix) and PREFIX_TO_FIRM[prefix] != firm:
                remaining_mismatch += 1

print(f'\n{"="*60}')
print(f'FINAL ({len(evals)} rows):')
print(f'  Account #:     {has_a:4d} ({has_a*100//len(evals)}%)')
print(f'  Account #.1:   {has_a1:4d} ({has_a1*100//len(evals)}%)')
print(f'  Has either:    {has_either:4d} ({has_either*100//len(evals)}%)')
print(f'  Missing BOTH:  {miss_both:4d} ({miss_both*100//len(evals)}%)')
print(f'  Prefix mismatches: {remaining_mismatch}')
print(f'{"="*60}')

# Show remaining missing rows
missing = [(i, ev) for i, ev in enumerate(evals) 
           if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip()]
print(f'\nRows still missing BOTH accounts ({len(missing)}):')
for i, ev in missing:
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    print(f'  Row {i:>3}: {firm:<22} {status:<14} {purchased}')

# Save to DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
            (json.dumps(evals),))
from datetime import datetime
cur.execute("SELECT MAX(version) FROM data_history WHERE client_id='Chris'")
new_ver = (cur.fetchone()[0] or 0) + 1
cur.execute("""INSERT INTO data_history 
    (client_id, version, action, changed_by, changed_by_type, ip_address, change_source, change_description, evaluations, created_at)
    VALUES ('Chris', ?, 'UPDATE', 'system_fix', 'super_admin', '127.0.0.1', 'log_account_fill', ?, ?, ?)""",
    (new_ver, f'Applied {applied_a + applied_a1 + extra_applied} accounts from logs (firm-prefix filtered), cleared {cleared_count} corrupted',
     json.dumps(evals), datetime.now().isoformat()))
db.commit()
db.close()

# Save CSV
cols = list(evals[0].keys()) if evals else []
# Ensure all columns
all_cols = set()
for ev in evals:
    all_cols.update(ev.keys())
cols = sorted(all_cols)

with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=cols)
    writer.writeheader()
    writer.writerows(evals)

print(f'\nSaved DB and CSV ({OUTPUT_CSV})')
