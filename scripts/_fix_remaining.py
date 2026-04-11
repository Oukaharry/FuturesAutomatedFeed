"""Fix the remaining 101 unmatched rows by using a looser match (fewer fields).
The unmatched rows had some field values changed by server updates since the CSV was exported."""
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

def make_full_key(row, fields):
    return tuple((row.get(f) or '').strip() for f in fields if f not in SKIP_FIELDS)

match_fields = [f for f in orig_fields if f not in SKIP_FIELDS]

# First pass: exact match (already done, rebuild used set)
orig_by_key = defaultdict(list)
for i, row in enumerate(orig_rows):
    key = make_full_key(row, match_fields)
    orig_by_key[key].append(i)

used_orig = set()
matched_db = set()
match_pairs = []

for db_idx, ev in enumerate(db_evals):
    key = make_full_key(ev, match_fields)
    candidates = orig_by_key.get(key, [])
    for c in candidates:
        if c not in used_orig:
            match_pairs.append((db_idx, c))
            used_orig.add(c)
            matched_db.add(db_idx)
            break

print(f'Exact matched: {len(matched_db)}/649')
remaining_db = [i for i in range(len(db_evals)) if i not in matched_db]
print(f'Remaining: {len(remaining_db)}')

# For remaining, try matching on stable core fields only 
# The fields that are most likely stable: Prop Firm, Date Purchased, Account Size
# Use the Account values themselves from the DB (which have ORIGINAL or log values)
# to positionally match within (firm, date, size) groups

def make_core_key(row):
    return (
        (row.get('Prop Firm') or '').strip(),
        (row.get('Date Purchased') or '').strip(),
        (row.get('Account Size') or '').strip(),
    )

# Build original lookup by core key (only include unused orig rows)
unused_orig_by_core = defaultdict(list)
for i, row in enumerate(orig_rows):
    if i not in used_orig:
        core = make_core_key(row)
        unused_orig_by_core[core].append(i)

# For each unmatched DB row, find candidates by core key
# Then pick the best match by comparing Account # values
loose_matches = 0
for db_idx in remaining_db:
    ev = db_evals[db_idx]
    core = make_core_key(ev)
    candidates = unused_orig_by_core.get(core, [])
    
    if not candidates:
        continue
    
    # Try to match by Account # or Account #.1 from current DB
    curr_a = (ev.get('Account #') or '').strip()
    curr_a1 = (ev.get('Account #.1') or '').strip()
    
    best = None
    for c in candidates:
        if c in used_orig:
            continue
        orig_a = (orig_rows[c].get('Account #') or '').strip()
        orig_a1 = (orig_rows[c].get('Account #.1') or '').strip()
        
        # Score: how many account fields match
        score = 0
        if curr_a and orig_a and curr_a == orig_a:
            score += 2
        if curr_a1 and orig_a1 and curr_a1 == orig_a1:
            score += 2
        # Partial: current contains original or vice versa
        if curr_a and orig_a and (curr_a in orig_a or orig_a in curr_a):
            score += 1
        if curr_a1 and orig_a1 and (curr_a1 in orig_a1 or orig_a1 in curr_a1):
            score += 1
        
        if best is None or score > best[0]:
            best = (score, c)
    
    if best:
        _, orig_idx = best
        used_orig.add(orig_idx)
        match_pairs.append((db_idx, orig_idx))
        matched_db.add(db_idx)
        loose_matches += 1
        
        # Apply original accounts
        orig_row = orig_rows[orig_idx]
        for field in ['Account #', 'Account #.1']:
            orig_val = (orig_row.get(field) or '').strip()
            if orig_val:
                db_evals[db_idx][field] = orig_val

print(f'Loose matched: {loose_matches}')
still_unmatched = [i for i in range(len(db_evals)) if i not in matched_db]
print(f'Still unmatched: {len(still_unmatched)}')

if still_unmatched:
    print(f'\n=== Still unmatched ===')
    for idx in still_unmatched[:20]:
        ev = db_evals[idx]
        firm = (ev.get('Prop Firm') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        print(f'  Row {idx}: {firm} {date} A={a!r} A.1={a1!r}')

# Save
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(db_evals),))
db.commit()
db.close()

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

# Final
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
print(f'\nDB and CSV updated.')
