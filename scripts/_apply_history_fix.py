"""Apply historical account recoveries from data_history versions + analyze remaining."""
import json, re, sqlite3, csv
from collections import Counter, defaultdict

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

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
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

# Get all versions
cur.execute("SELECT version, evaluations, created_at FROM data_history WHERE client_id='Chris' ORDER BY version")
versions = cur.fetchall()

def make_key(ev):
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    eval_num = (ev.get('Eval #') or str(ev.get('eval_num', ''))).strip()
    size = (ev.get('Account Size') or '').strip()
    return (firm, date, eval_num, size)

# Identify rows needing help
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

# Scan versions
best_values = defaultdict(lambda: {'Account #': None, 'Account #.1': None})
for version_id, evals_json, created_at in versions:
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

# Apply changes
changes = []
for row_idx, firm, expected, has_a, has_a1 in needs_help:
    vals = best_values.get(row_idx, {})
    if not has_a and vals.get('Account #'):
        changes.append((row_idx, 'Account #', evals[row_idx].get('Account #', ''), vals['Account #']))
        evals[row_idx]['Account #'] = vals['Account #']
    if not has_a1 and vals.get('Account #.1'):
        changes.append((row_idx, 'Account #.1', evals[row_idx].get('Account #.1', ''), vals['Account #.1']))
        evals[row_idx]['Account #.1'] = vals['Account #.1']

print(f'Applied {len(changes)} changes from historical versions')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
db.commit()
db.close()

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

for row_idx, field, old, new in changes:
    if row_idx < len(csv_rows):
        csv_rows[row_idx][field] = new

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

# Final stats
still_missing = {'both': 0, 'a_only': 0, 'a1_only': 0, 'ok': 0}
missing_detail = []
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    
    if a_ok and a1_ok:
        still_missing['ok'] += 1
    elif a_ok:
        still_missing['a1_only'] += 1
    elif a1_ok:
        still_missing['a_only'] += 1
    else:
        still_missing['both'] += 1
        phase = (ev.get('Phase') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        status = (ev.get('Status') or '').strip()
        missing_detail.append((i, firm, phase, status, date, a, a1))

print(f'\n=== FINAL STATE ===')
print(f'Total: {len(evals)}')
print(f'Both valid: {still_missing["ok"]}')
print(f'Missing Account # only: {still_missing["a_only"]}')
print(f'Missing Account #.1 only: {still_missing["a1_only"]}')
print(f'Missing BOTH: {still_missing["both"]}')
print(f'Coverage (has at least one): {len(evals) - still_missing["both"]}/{len(evals)} ({100*(len(evals)-still_missing["both"])/len(evals):.1f}%)')

# Breakdown
firms = Counter()
for _, firm, phase, status, date, *_ in missing_detail:
    firms[firm] += 1
print(f'\nMissing BOTH by firm:')
for f, c in firms.most_common():
    print(f'  {f}: {c}')

# Show all Topstep missing rows status/phase
print(f'\n=== Topstep missing rows detail ===')
topstep_phases = Counter()
for i, firm, phase, status, date, a, a1 in missing_detail:
    if firm == 'Topstep':
        topstep_phases[f'{phase or "empty"} / {status or "empty"}'] += 1
print('  Phase / Status breakdown:')
for ps, c in topstep_phases.most_common():
    print(f'    {ps}: {c}')

# Show Topstep date range
ts_dates = [date for _, firm, _, _, date, _, _ in missing_detail if firm == 'Topstep' and date]
if ts_dates:
    print(f'  Date range: {min(ts_dates)} to {max(ts_dates)}')

# Show Funding Ticks missing rows
print(f'\n=== Funding Ticks missing rows detail ===')
ftks_phases = Counter()
for i, firm, phase, status, date, a, a1 in missing_detail:
    if firm == 'Funding Ticks':
        ftks_phases[f'{phase or "empty"} / {status or "empty"}'] += 1
print('  Phase / Status breakdown:')
for ps, c in ftks_phases.most_common():
    print(f'    {ps}: {c}')

ftks_dates = [date for _, firm, _, _, date, _, _ in missing_detail if firm == 'Funding Ticks' and date]
if ftks_dates:
    print(f'  Date range: {min(ftks_dates)} to {max(ftks_dates)}')

# Check what values are currently in Account fields for these rows
print(f'\n=== Current Account values in missing rows (non-empty) ===')
nonempty = 0
for i, firm, phase, status, date, a, a1 in missing_detail:
    if a or a1:
        if nonempty < 20:
            print(f'  Row {i:>3}: {firm:<22} A={a!r:<30} A.1={a1!r}')
        nonempty += 1
if nonempty > 20:
    print(f'  ... and {nonempty - 20} more')
print(f'  Total with non-empty (but invalid) values: {nonempty}')
