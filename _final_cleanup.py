"""Final cleanup: 
1. Clear 4 ELTD-corrupted values (V2-ELTDEN..., TDF-ELTDEN...)
2. Try to recover remaining 57 missing-both from history with FIXED regex
3. Handle raw Funding Ticks numbers (prefix them as FTKS-XXXXXXX)
4. Report final state"""
import json, re, sqlite3, csv
from collections import Counter, defaultdict

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

# FIXED regex - allows digits in prefix (V2)
VALID_ACCT = re.compile(r'^[A-Z][A-Z0-9]{1,4}-[A-Z0-9]{3,8}$')  # Allow up to 8 for FTKS raw numbers

FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU',
    'Tradeify': 'TDFY',
    'Topstep': 'V2',
    'TradeDay': 'TDF',
    'FundedNext': 'FNFT',
    'Apex Trader Funding': 'APEX',
    'Funding Ticks': 'FTKS',
    'Alpha Futures': 'AFAD',
}

# Load data
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

# Step 1: Clean ELTD corrupted values
ELTD_RE = re.compile(r'ELTD')
eltd_cleaned = 0
for i, ev in enumerate(evals):
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if val and ELTD_RE.search(val):
            print(f'  Clearing ELTD corrupted: Row {i} {field} = {val!r}')
            evals[i][field] = ''
            eltd_cleaned += 1

# Step 2: Fix raw Funding Ticks numbers - prefix with FTKS-
ftks_fixed = 0
RAW_NUMBER = re.compile(r'^\d{6,10}$')
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    if firm != 'Funding Ticks':
        continue
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if val and RAW_NUMBER.match(val):
            new_val = f'FTKS-{val}'
            print(f'  Prefixing FTKS raw: Row {i} {field} = {val!r} -> {new_val!r}')
            evals[i][field] = new_val
            ftks_fixed += 1

print(f'\nELTD cleaned: {eltd_cleaned}')
print(f'FTKS raw prefixed: {ftks_fixed}')

# Step 3: Try history recovery for remaining missing with FIXED regex
cur.execute("SELECT version, evaluations FROM data_history WHERE client_id='Chris' ORDER BY version")
versions = cur.fetchall()

def make_key(ev):
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    eval_num = (ev.get('Eval #') or str(ev.get('eval_num', ''))).strip()
    size = (ev.get('Account Size') or '').strip()
    return (firm, date, eval_num, size)

needs_help = []
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    if not a_ok or not a1_ok:
        needs_help.append((i, firm, expected, a_ok, a1_ok))

current_keys = {i: make_key(evals[i]) for i, *_ in needs_help}
best_values = defaultdict(lambda: {'Account #': None, 'Account #.1': None})

for version_id, evals_json in versions:
    try:
        ver_evals = json.loads(evals_json)
    except:
        continue
    ver_lookup = defaultdict(list)
    for ev in ver_evals:
        ver_lookup[make_key(ev)].append(ev)
    for row_idx, firm, expected, has_a, has_a1 in needs_help:
        key = current_keys[row_idx]
        for ver_ev in ver_lookup.get(key, []):
            for field in ['Account #', 'Account #.1']:
                val = (ver_ev.get(field) or '').strip()
                if val and VALID_ACCT.match(val) and expected and val.startswith(expected + '-'):
                    best_values[row_idx][field] = val

history_changes = 0
for row_idx, firm, expected, has_a, has_a1 in needs_help:
    vals = best_values.get(row_idx, {})
    if not has_a and vals.get('Account #'):
        evals[row_idx]['Account #'] = vals['Account #']
        history_changes += 1
    if not has_a1 and vals.get('Account #.1'):
        evals[row_idx]['Account #.1'] = vals['Account #.1']
        history_changes += 1

print(f'History recoveries (additional): {history_changes}')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
db.commit()
db.close()

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

# Re-apply ALL changes to CSV  
for i, ev in enumerate(evals):
    if i < len(csv_rows):
        csv_rows[i]['Account #'] = ev.get('Account #', '')
        csv_rows[i]['Account #.1'] = ev.get('Account #.1', '')

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

# Final comprehensive stats
print(f'\n{"="*60}')
print(f'FINAL COMPREHENSIVE REPORT')
print(f'{"="*60}')

has_both = 0
missing_a_only = 0
missing_a1_only = 0
missing_both = 0
corrupted_count = 0
prefix_mismatch = 0

missing_detail = []
corrupted_list = []
mismatch_list = []

for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    
    a_valid = bool(VALID_ACCT.match(a)) if a else False
    a1_valid = bool(VALID_ACCT.match(a1)) if a1 else False
    a_prefix = a.startswith(expected + '-') if a and expected else True
    a1_prefix = a1.startswith(expected + '-') if a1 and expected else True
    
    a_ok = a_valid and a_prefix if a else False
    a1_ok = a1_valid and a1_prefix if a1 else False
    
    # Check for corrupted
    if a and not a_valid:
        corrupted_count += 1
        corrupted_list.append((i, 'Account #', a, firm))
    if a1 and not a1_valid:
        corrupted_count += 1
        corrupted_list.append((i, 'Account #.1', a1, firm))
    
    # Check prefix mismatches
    if a_valid and not a_prefix:
        prefix_mismatch += 1
        mismatch_list.append((i, 'Account #', a, firm, expected))
    if a1_valid and not a1_prefix:
        prefix_mismatch += 1
        mismatch_list.append((i, 'Account #.1', a1, firm, expected))
    
    if a_ok and a1_ok:
        has_both += 1
    elif a_ok:
        missing_a1_only += 1
    elif a1_ok:
        missing_a_only += 1
    else:
        missing_both += 1
        missing_detail.append((i, firm))

total = len(evals)
has_either = has_both + missing_a_only + missing_a1_only

print(f'Total evaluations: {total}')
print(f'Both accounts valid: {has_both} ({100*has_both/total:.1f}%)')
print(f'Missing Account # only: {missing_a_only}')
print(f'Missing Account #.1 only: {missing_a1_only}')
print(f'Missing BOTH: {missing_both} ({100*missing_both/total:.1f}%)')
print(f'')
print(f'Coverage (at least one): {has_either}/{total} ({100*has_either/total:.1f}%)')
print(f'Corrupted values: {corrupted_count}')
print(f'Prefix mismatches: {prefix_mismatch}')

if corrupted_list:
    print(f'\nCorrupted values:')
    for i, field, val, firm in corrupted_list:
        print(f'  Row {i:>3}: {field:12} = {val!r} ({firm})')

if mismatch_list:
    print(f'\nPrefix mismatches:')
    for i, field, val, firm, expected in mismatch_list:
        print(f'  Row {i:>3}: {field:12} = {val!r} ({firm}, expected {expected})')

firms = Counter(firm for _, firm in missing_detail)
print(f'\nMissing BOTH by firm:')
for f, c in firms.most_common():
    print(f'  {f}: {c}')
