"""Restore original account numbers from Chris_evaluations.csv (1455 rows) 
to the current 649 rows.

Rules:
- If original had a non-empty account value -> USE IT (original dashboard format)
- If original was empty but current has a value (log-derived) -> KEEP current
- Never overwrite a non-empty original with a log-derived value
"""
import csv, json, sqlite3
from collections import Counter, defaultdict

ORIG_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
FIXED_CSV = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
DB_PATH = 'dashboard/dashboard.db'

# Read original
with open(ORIG_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    orig_fields = reader.fieldnames
    orig_rows = list(reader)

# Read current DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])

print(f'Original CSV: {len(orig_rows)} rows')
print(f'Current DB:   {len(db_evals)} evals')

# Build identity key
def make_key(r, is_db=False):
    firm = (r.get('Prop Firm') or '').strip()
    date = (r.get('Date Purchased') or '').strip()
    eval_num = (r.get('Eval #') or str(r.get('eval_num', '')) or '').strip()
    size = (r.get('Account Size') or '').strip()
    return (firm, date, eval_num, size)

# Original has duplicates - deduplicate by taking the first occurrence of each key
# (same logic as when we deduped 1403->656)
orig_by_key = {}
for i, r in enumerate(orig_rows):
    key = make_key(r)
    if key not in orig_by_key:
        orig_by_key[key] = r

print(f'Unique original rows: {len(orig_by_key)}')

# Match current DB rows to original
matched = 0
unmatched = 0
restored_a = 0
restored_a1 = 0
kept_log_a = 0
kept_log_a1 = 0
both_empty = 0

changes = []

for i, ev in enumerate(db_evals):
    key = make_key(ev, is_db=True)
    orig = orig_by_key.get(key)
    
    if not orig:
        unmatched += 1
        continue
    
    matched += 1
    
    for field in ['Account #', 'Account #.1']:
        orig_val = (orig.get(field) or '').strip()
        curr_val = (ev.get(field) or '').strip()
        
        if orig_val:
            # Original had a value -> restore it
            if curr_val != orig_val:
                changes.append((i, field, curr_val, orig_val, 'restore'))
                db_evals[i][field] = orig_val
                if field == 'Account #':
                    restored_a += 1
                else:
                    restored_a1 += 1
        elif curr_val:
            # Original empty, current has log-derived -> keep
            if field == 'Account #':
                kept_log_a += 1
            else:
                kept_log_a1 += 1
        else:
            both_empty += 1

print(f'\nMatched: {matched}/{len(db_evals)}')
print(f'Unmatched: {unmatched}')
print(f'Restored Account #: {restored_a}')
print(f'Restored Account #.1: {restored_a1}')
print(f'Kept log-derived Account #: {kept_log_a}')
print(f'Kept log-derived Account #.1: {kept_log_a1}')
print(f'Both empty (no source): {both_empty}')
print(f'Total changes: {len(changes)}')

# Show samples
print(f'\n=== Sample changes ===')
for i, field, old, new, action in changes[:30]:
    firm = (db_evals[i].get('Prop Firm') or '').strip()
    if old != new:  # meaningful change
        marker = '(was empty)' if not old else '(was different)'
        print(f'  Row {i:>3}: {field:12} {new!r:<45} <- {old!r:<35} {firm} {marker}')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(db_evals),))
db.commit()
db.close()

# Save to fixed CSV 
with open(FIXED_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fixed_fields = reader.fieldnames
    fixed_rows = list(reader)

for i, ev in enumerate(db_evals):
    if i < len(fixed_rows):
        fixed_rows[i]['Account #'] = ev.get('Account #', '')
        fixed_rows[i]['Account #.1'] = ev.get('Account #.1', '')

with open(FIXED_CSV, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fixed_fields)
    writer.writeheader()
    writer.writerows(fixed_rows)

# Final stats
print(f'\n{"="*60}')
print(f'FINAL STATE')
print(f'{"="*60}')
total = len(db_evals)
pop_a = sum(1 for ev in db_evals if (ev.get('Account #') or '').strip())
pop_a1 = sum(1 for ev in db_evals if (ev.get('Account #.1') or '').strip())
both = sum(1 for ev in db_evals if (ev.get('Account #') or '').strip() and (ev.get('Account #.1') or '').strip())
neither = sum(1 for ev in db_evals if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip())

print(f'Total: {total}')
print(f'Account # populated: {pop_a}/{total} ({100*pop_a/total:.1f}%)')
print(f'Account #.1 populated: {pop_a1}/{total} ({100*pop_a1/total:.1f}%)')
print(f'Both populated: {both}/{total} ({100*both/total:.1f}%)')
print(f'Neither populated: {neither}/{total} ({100*neither/total:.1f}%)')
print(f'Has at least one: {total-neither}/{total} ({100*(total-neither)/total:.1f}%)')

# Show format breakdown
print(f'\n=== Account # format samples ===')
formats = Counter()
for ev in db_evals:
    a = (ev.get('Account #') or '').strip()
    if not a:
        formats['(empty)'] += 1
    elif 'EVSTP' in a or 'EVSCL' in a or 'SFSCL' in a or 'SFSTP' in a:
        formats['dashboard-long (MFFUEVxxx)'] += 1
    elif 'FTPROPLUS' in a:
        formats['dashboard-long (FTPROPLUS)'] += 1
    elif 'ELTD' in a:
        formats['dashboard-long (ELTD)'] += 1
    elif len(a) <= 10 and '-' in a:
        formats['log-derived (PREFIX-XXXXX)'] += 1
    else:
        formats[f'other ({a[:20]})'] += 1

print(f'Account # formats:')
for fmt, c in formats.most_common():
    print(f'  {fmt}: {c}')

formats2 = Counter()
for ev in db_evals:
    a1 = (ev.get('Account #.1') or '').strip()
    if not a1:
        formats2['(empty)'] += 1
    elif 'EVSTP' in a1 or 'EVSCL' in a1 or 'SFSCL' in a1 or 'SFSTP' in a1:
        formats2['dashboard-long (MFFUxxx)'] += 1
    elif 'FTPROPLUS' in a1:
        formats2['dashboard-long (FTPROPLUS)'] += 1
    elif 'ELTD' in a1:
        formats2['dashboard-long (ELTD)'] += 1
    elif len(a1) <= 10 and '-' in a1:
        formats2['log-derived (PREFIX-XXXXX)'] += 1
    else:
        formats2[f'other ({a1[:20]})'] += 1

print(f'\nAccount #.1 formats:')
for fmt, c in formats2.most_common():
    print(f'  {fmt}: {c}')

print(f'\nDB and CSV updated.')
