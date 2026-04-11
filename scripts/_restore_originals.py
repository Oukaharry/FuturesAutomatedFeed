"""Find the pre-audit baseline and restore original dashboard account values.

v61 is the last CSV import (our latest state before today's session).
v60 was the CSV import after the first round of fixes.
v59 is where 493 log accounts were applied + 287 corrupted cleared.
v58 is where 29 prefix mismatches fixed + 96 unresolvable cleared.
v57 is the CSV import after dedup.

The ORIGINAL dashboard state (before ANY of our account scripts) is v57 or earlier.
v56 is the dedup (1403->656). Before that, v53/v52 are pre-dedup CSV imports.

We need v57 (post-dedup, pre-account-fix) as the baseline - it has the original
dashboard account values before we started clearing things.

Then for each row:
- If v57 had a non-empty account value, restore it (dashboard original)
- If current value is from our log extraction and v57 was empty, keep it (log-derived)
"""
import json, re, sqlite3, csv
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get current state
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
current_evals = json.loads(cur.fetchone()[0])

# Get v57 (pre-account-fix baseline) - has 656 rows
cur.execute("SELECT evaluations FROM data_history WHERE client_id='Chris' AND version=57")
v57_evals = json.loads(cur.fetchone()[0])

# v57 has 656 rows, current has 649 (7 TradeDay IP rows were removed)
# We need to match by identity
print(f'Current: {len(current_evals)} evals')
print(f'V57 baseline: {len(v57_evals)} evals')

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

def make_key(ev):
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    eval_num = (ev.get('Eval #') or str(ev.get('eval_num', ''))).strip()
    size = (ev.get('Account Size') or '').strip()
    phase = (ev.get('Phase') or '').strip()
    return (firm, date, eval_num, size, phase)

# Build v57 lookup by key
v57_lookup = {}
for ev in v57_evals:
    key = make_key(ev)
    # Store with both fields
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    if key not in v57_lookup:
        v57_lookup[key] = (a, a1)

# Now for each current row, check if v57 had a value we cleared
restorations = 0
log_kept = 0
already_ok = 0
changes = []

for i, ev in enumerate(current_evals):
    key = make_key(ev)
    cur_a = (ev.get('Account #') or '').strip()
    cur_a1 = (ev.get('Account #.1') or '').strip()
    
    v57_a, v57_a1 = v57_lookup.get(key, ('', ''))
    
    for field, cur_val, v57_val in [
        ('Account #', cur_a, v57_a),
        ('Account #.1', cur_a1, v57_a1),
    ]:
        if not v57_val:
            # v57 had nothing - keep whatever we have (could be log-derived or empty)
            if cur_val:
                log_kept += 1
            continue
        
        if cur_val == v57_val:
            already_ok += 1
            continue
        
        if not cur_val and v57_val:
            # We cleared a dashboard-original value - RESTORE it
            changes.append((i, field, cur_val, v57_val, 'restored'))
            current_evals[i][field] = v57_val
            restorations += 1
        elif cur_val != v57_val and v57_val:
            # We replaced a dashboard value with a log value
            # Restore the original dashboard value
            changes.append((i, field, cur_val, v57_val, 'reverted'))
            current_evals[i][field] = v57_val
            restorations += 1

print(f'\nRestorations: {restorations}')
print(f'Log-derived values kept: {log_kept}')
print(f'Already matching: {already_ok}')

# Show what was restored
restored_types = Counter()
for i, field, old, new, action in changes:
    restored_types[action] += 1

print(f'\nRestored: {restored_types["restored"]}')
print(f'Reverted to original: {restored_types["reverted"]}')

# Show samples
print(f'\n=== Sample restorations ===')
for i, field, old, new, action in changes[:30]:
    firm = (current_evals[i].get('Prop Firm') or '').strip()
    print(f'  Row {i:>3}: {field:12} {action:10} {old!r:30} -> {new!r:30} ({firm})')

# Save
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(current_evals),))
db.commit()
db.close()

# Update CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

for i, ev in enumerate(current_evals):
    if i < len(csv_rows):
        csv_rows[i]['Account #'] = ev.get('Account #', '')
        csv_rows[i]['Account #.1'] = ev.get('Account #.1', '')

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

# Final count 
print(f'\n{"="*60}')
print(f'FINAL STATE')
print(f'{"="*60}')
populated_a = sum(1 for ev in current_evals if (ev.get('Account #') or '').strip())
populated_a1 = sum(1 for ev in current_evals if (ev.get('Account #.1') or '').strip())
both = sum(1 for ev in current_evals 
           if (ev.get('Account #') or '').strip() and (ev.get('Account #.1') or '').strip())
neither = sum(1 for ev in current_evals 
              if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip())
total = len(current_evals)

print(f'Total: {total}')
print(f'Account # populated: {populated_a}/{total} ({100*populated_a/total:.1f}%)')
print(f'Account #.1 populated: {populated_a1}/{total} ({100*populated_a1/total:.1f}%)')
print(f'Both populated: {both}/{total} ({100*both/total:.1f}%)')
print(f'Neither populated: {neither}/{total} ({100*neither/total:.1f}%)')
print(f'Has at least one: {total-neither}/{total} ({100*(total-neither)/total:.1f}%)')

print(f'\nDB and CSV updated')
