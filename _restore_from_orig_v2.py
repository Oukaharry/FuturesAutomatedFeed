"""Match by Row # in DB (sequential index) to positional order in original CSV.
Only difference is Row # (empty in orig, populated in DB).
The original CSV has 1455 rows (duplicated). The DB has 649 (deduped).

Strategy: Match ALL fields except Row # and Accounts. Since Row # is the ONLY
difference (aside from accounts), this should work perfectly now."""
import csv, json, sqlite3
from collections import Counter, defaultdict

ORIG_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
FIXED_CSV = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
DB_PATH = 'dashboard/dashboard.db'

with open(ORIG_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    orig_fields = reader.fieldnames
    orig_rows = list(reader)

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])

SKIP_FIELDS = {'Account #', 'Account #.1', 'Row #'}

def make_key(row, fields):
    return tuple((row.get(f) or '').strip() for f in fields if f not in SKIP_FIELDS)

match_fields = [f for f in orig_fields if f not in SKIP_FIELDS]

# Build original lookup
orig_by_key = defaultdict(list)
for i, row in enumerate(orig_rows):
    key = make_key(row, match_fields)
    orig_by_key[key].append(i)

# Match DB rows
matched = []
unmatched = []
used_orig = set()

for db_idx, ev in enumerate(db_evals):
    key = make_key(ev, match_fields)
    candidates = orig_by_key.get(key, [])
    
    # Pick first unused candidate
    found = False
    for c in candidates:
        if c not in used_orig:
            matched.append((db_idx, c))
            used_orig.add(c)
            found = True
            break
    
    if not found:
        unmatched.append(db_idx)

print(f'Matched: {len(matched)}/649')
print(f'Unmatched: {len(unmatched)}')

if unmatched:
    print(f'\n=== Unmatched DB rows ===')
    for idx in unmatched[:15]:
        ev = db_evals[idx]
        firm = (ev.get('Prop Firm') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        status = (ev.get('Status') or '').strip()
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        print(f'  DB row {idx}: {firm} {date} Status={status!r} A={a!r} A.1={a1!r}')

# Now restore original accounts for matched rows
changes = 0
restored_a = 0
restored_a1 = 0
kept_current = 0

for db_idx, orig_idx in matched:
    orig_row = orig_rows[orig_idx]
    
    for field in ['Account #', 'Account #.1']:
        orig_val = (orig_row.get(field) or '').strip()
        curr_val = (db_evals[db_idx].get(field) or '').strip()
        
        if orig_val and orig_val != curr_val:
            db_evals[db_idx][field] = orig_val
            changes += 1
            if field == 'Account #':
                restored_a += 1
            else:
                restored_a1 += 1
        elif not orig_val and curr_val:
            # Original was empty, current has log-derived - keep it
            kept_current += 1

print(f'\nTotal changes: {changes}')
print(f'Restored Account #: {restored_a}')
print(f'Restored Account #.1: {restored_a1}')
print(f'Kept log-derived (orig was empty): {kept_current}')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(db_evals),))
db.commit()
db.close()

# Save to CSV
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
total = len(db_evals)
pop_a = sum(1 for ev in db_evals if (ev.get('Account #') or '').strip())
pop_a1 = sum(1 for ev in db_evals if (ev.get('Account #.1') or '').strip())
both = sum(1 for ev in db_evals if (ev.get('Account #') or '').strip() and (ev.get('Account #.1') or '').strip())
neither = sum(1 for ev in db_evals if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip())

print(f'\n{"="*60}')
print(f'FINAL STATE')
print(f'{"="*60}')
print(f'Total: {total}')
print(f'Account # populated: {pop_a}/{total} ({100*pop_a/total:.1f}%)')
print(f'Account #.1 populated: {pop_a1}/{total} ({100*pop_a1/total:.1f}%)')
print(f'Both populated: {both}/{total} ({100*both/total:.1f}%)')
print(f'Neither populated: {neither}/{total} ({100*neither/total:.1f}%)')
print(f'Has at least one: {total-neither}/{total} ({100*(total-neither)/total:.1f}%)')

# Show format breakdown for Account #
formats = Counter()
for ev in db_evals:
    a = (ev.get('Account #') or '').strip()
    if not a:
        formats['(empty)'] += 1
    elif 'EVS' in a or 'SFS' in a or 'EVC' in a:
        formats['dashboard-long'] += 1
    elif 'FTPROPLUS' in a:
        formats['FTPROPLUS'] += 1
    elif 'ELTD' in a:
        formats['ELTD'] += 1
    elif 'CHCHRISREAM' in a:
        formats['CHCHRISREAM'] += 1
    elif 'TDFYSL' in a:
        formats['TDFYSL'] += 1
    elif '50KTC' in a:
        formats['50KTC-V2'] += 1
    elif 'AFADV' in a:
        formats['AFADV'] += 1
    elif len(a) <= 12 and '-' in a:
        formats['log-derived (PREFIX-XXXXX)'] += 1
    else:
        formats[f'other'] += 1

print(f'\nAccount # formats:')
for fmt, c in formats.most_common():
    print(f'  {fmt}: {c}')

# Same for Account #.1
formats2 = Counter()
for ev in db_evals:
    a1 = (ev.get('Account #.1') or '').strip()
    if not a1:
        formats2['(empty)'] += 1
    elif 'EVS' in a1 or 'SFS' in a1 or 'EVC' in a1:
        formats2['dashboard-long'] += 1
    elif 'FTPROPLUS' in a1:
        formats2['FTPROPLUS'] += 1
    elif 'ELTD' in a1:
        formats2['ELTD'] += 1
    elif 'CHCHRISREAM' in a1:
        formats2['CHCHRISREAM'] += 1
    elif 'TDFYSL' in a1:
        formats2['TDFYSL'] += 1
    elif '50KTC' in a1:
        formats2['50KTC-V2'] += 1
    elif 'AFADV' in a1:
        formats2['AFADV'] += 1
    elif len(a1) <= 12 and '-' in a1:
        formats2['log-derived (PREFIX-XXXXX)'] += 1
    else:
        formats2['other'] += 1

print(f'\nAccount #.1 formats:')
for fmt, c in formats2.most_common():
    print(f'  {fmt}: {c}')

# Show some sample rows
print(f'\n=== Sample rows (first 20) ===')
for i in range(min(20, total)):
    ev = db_evals[i]
    firm = (ev.get('Prop Firm') or '').strip()
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    print(f'  Row {i:>3}: {firm:<22} A={a!r:<35} A.1={a1!r}')

print(f'\nDB and CSV updated.')
