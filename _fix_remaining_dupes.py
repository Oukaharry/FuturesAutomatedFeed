"""Handle remaining duplicates (rows 212/230 and 213/231) and fix row 624 (0494 missing V2- prefix)."""
import json, sqlite3, csv

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
print(f'Before: {len(evals)} evals')

# ---- Check duplicates: rows 212/230 and 213/231 ----
for pair in [(212, 230), (213, 231)]:
    a, b = pair
    ev_a = evals[a]
    ev_b = evals[b]
    print(f'\n--- Row {a} vs Row {b} ---')
    diffs = {}
    all_keys = set(ev_a.keys()) | set(ev_b.keys())
    for k in sorted(all_keys):
        va = str(ev_a.get(k, '') or '').strip()
        vb = str(ev_b.get(k, '') or '').strip()
        if va != vb:
            diffs[k] = (va, vb)
            print(f'  {k}: {va!r} vs {vb!r}')
    print(f'  Total diffs: {len(diffs)}, same: {len(all_keys) - len(diffs)}')

# Merge: keep the row with more data, merge any missing fields
to_remove = []
for keep, remove in [(212, 230), (213, 231)]:
    ev_keep = evals[keep]
    ev_remove = evals[remove]
    
    # Fill any empty in keep from remove
    for k, v in ev_remove.items():
        val = str(v or '').strip()
        current = str(ev_keep.get(k, '') or '').strip()
        if val and not current:
            ev_keep[k] = v
    
    to_remove.append(remove)

# Fix row 624: Account # is '0494' should be 'V2-0494'
if str(evals[624].get('Account #', '')).strip() == '0494':
    print(f'\nFixing row 624: Account # "0494" -> "V2-0494"')
    evals[624]['Account #'] = 'V2-0494'

# Remove duplicates in reverse order
to_remove.sort(reverse=True)
for idx in to_remove:
    evals.pop(idx)
    print(f'Removed duplicate row {idx}')

print(f'\nAfter: {len(evals)} evals')

# Re-number
for i, ev in enumerate(evals):
    ev['Row #'] = str(i)

# Save
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
db.commit()
db.close()

with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for ev in evals:
        row = {fn: ev.get(fn, '') for fn in fieldnames}
        writer.writerow(row)

print(f'DB + CSV updated. {len(evals)} evals.')
