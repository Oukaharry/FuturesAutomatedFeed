"""Check data_history versions for original V2 and FTKS account values
before corruption occurred. The corruption happened during concurrent pushes,
so earlier versions should have the correct accounts."""
import json, re, sqlite3
from collections import Counter, defaultdict

DB_PATH = 'dashboard/dashboard.db'

VALID_ACCT = re.compile(r'^[A-Z]{2,5}-[A-Z0-9]{3,6}$')
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

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get current evals
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
current_evals = json.loads(cur.fetchone()[0])

# Get all versions
cur.execute("SELECT version, evaluations, created_at FROM data_history WHERE client_id='Chris' ORDER BY version")
versions = cur.fetchall()
db.close()

print(f'Total versions: {len(versions)}')
print(f'Current evals: {len(current_evals)}')

# For each row that's missing accounts now, find the BEST historical account value
# Track: row_idx -> {field: best_account_value}
# "Best" = most recent version that had a VALID, firm-matching account

# First, identify which rows need help
needs_help = []
for i, ev in enumerate(current_evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    if not a_ok or not a1_ok:
        needs_help.append((i, firm, expected, a_ok, a1_ok))

print(f'Rows needing help: {len(needs_help)}')

# Strategy: Match historical rows by (Prop Firm, Date Purchased, Eval #) as identity
# First understand the identity matching
def make_key(ev):
    """Create identity key for matching across versions"""
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    eval_num = (ev.get('Eval #') or str(ev.get('eval_num', ''))).strip()
    size = (ev.get('Account Size') or '').strip()
    return (firm, date, eval_num, size)

# Build current keys for rows that need help
current_keys = {}
for i, firm, expected, has_a, has_a1 in needs_help:
    key = make_key(current_evals[i])
    current_keys[i] = key

# Scan all versions from OLDEST to NEWEST to find valid account values
# Collecting per-key: field -> best valid value
best_values = defaultdict(lambda: {'Account #': None, 'Account #.1': None})

# Process versions from earliest to latest
for version_id, evals_json, created_at in versions:
    try:
        ver_evals = json.loads(evals_json)
    except:
        continue
    
    # Build a key->eval lookup for this version
    ver_lookup = defaultdict(list)
    for ev in ver_evals:
        key = make_key(ev)
        ver_lookup[key].append(ev)
    
    # For each needing row, check if this version has a valid account for it
    for row_idx, firm, expected, has_a, has_a1 in needs_help:
        key = current_keys[row_idx]
        matches = ver_lookup.get(key, [])
        
        for ver_ev in matches:
            for field in ['Account #', 'Account #.1']:
                val = (ver_ev.get(field) or '').strip()
                if val and VALID_ACCT.match(val) and expected and val.startswith(expected + '-'):
                    best_values[row_idx][field] = (val, version_id, created_at)

# Count how many we found
found_a = sum(1 for k, v in best_values.items() if v['Account #'] is not None)
found_a1 = sum(1 for k, v in best_values.items() if v['Account #.1'] is not None)
print(f'\nFound valid historical Account # for {found_a} rows')
print(f'Found valid historical Account #.1 for {found_a1} rows')

# Breakdown by firm
firms_found = Counter()
for row_idx, vals in best_values.items():
    if vals['Account #'] or vals['Account #.1']:
        firm = current_evals[row_idx].get('Prop Firm', '').strip()
        firms_found[firm] += 1

print(f'\nFirm breakdown of historical recoveries:')
for f, c in firms_found.most_common():
    print(f'  {f}: {c}')

# Show samples
print(f'\n=== Sample recovered values ===')
shown = 0
for row_idx in sorted(best_values.keys()):
    vals = best_values[row_idx]
    if vals['Account #'] or vals['Account #.1']:
        ev = current_evals[row_idx]
        firm = (ev.get('Prop Firm') or '').strip()
        a_info = vals['Account #']
        a1_info = vals['Account #.1']
        a_str = f'{a_info[0]} (v{a_info[1]})' if a_info else 'NOT FOUND'
        a1_str = f'{a1_info[0]} (v{a1_info[1]})' if a1_info else 'NOT FOUND'
        if shown < 40:
            print(f'  Row {row_idx:>3}: {firm:<22} Acct#={a_str:<24} Acct#.1={a1_str}')
            shown += 1

# Show how many still remain unrecoverable
still_missing_both = 0
still_missing_a = 0
still_missing_a1 = 0
for row_idx, firm, expected, has_a, has_a1 in needs_help:
    got_a = has_a or (best_values.get(row_idx, {}).get('Account #') is not None)
    got_a1 = has_a1 or (best_values.get(row_idx, {}).get('Account #.1') is not None)
    if not got_a and not got_a1:
        still_missing_both += 1
    elif not got_a:
        still_missing_a += 1
    elif not got_a1:
        still_missing_a1 += 1

print(f'\n=== After historical recovery ===')
print(f'Still missing BOTH: {still_missing_both}')
print(f'Still missing Account # only: {still_missing_a}')
print(f'Still missing Account #.1 only: {still_missing_a1}')

# Firm breakdown of still truly missing both
still_firms = Counter()
for row_idx, firm, expected, has_a, has_a1 in needs_help:
    got_a = has_a or (best_values.get(row_idx, {}).get('Account #') is not None)
    got_a1 = has_a1 or (best_values.get(row_idx, {}).get('Account #.1') is not None)
    if not got_a and not got_a1:
        ev = current_evals[row_idx]
        f = (ev.get('Prop Firm') or '').strip()
        phase = (ev.get('Phase') or '').strip()
        still_firms[f'{f} ({phase})'] += 1

print(f'\nFirm+Phase of truly missing both:')
for f, c in still_firms.most_common():
    print(f'  {f}: {c}')
