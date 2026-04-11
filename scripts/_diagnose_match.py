"""Diagnose: compare DB row 0 vs original CSV row 0 to see which fields differ."""
import csv, json, sqlite3

ORIG_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
DB_PATH = 'dashboard/dashboard.db'

with open(ORIG_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    orig_fields = reader.fieldnames
    orig_rows = list(reader)

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])
db.close()

# Compare first row
db0 = db_evals[0]
orig0 = orig_rows[0]

print(f'=== Field comparison DB row 0 vs Orig row 0 ===')
differs = []
same = []
db_only = []
orig_only = []

for f in orig_fields:
    ov = (orig0.get(f) or '').strip()
    dv = (db0.get(f) or '').strip()
    if ov == dv:
        same.append(f)
    else:
        differs.append((f, ov, dv))

for f in db0:
    if f not in orig_fields:
        db_only.append(f)

print(f'Same: {len(same)}')
print(f'Different: {len(differs)}')
print(f'DB-only fields: {len(db_only)}')

print(f'\n--- Different fields ---')
for f, ov, dv in differs:
    print(f'  {f:30} ORIG={ov!r:30} DB={dv!r}')

print(f'\n--- DB-only fields ---')
for f in db_only:
    print(f'  {f}: {db0[f]!r}')

# Now let's try matching on just the few stable fields
# and see how many unique combos exist
from collections import Counter

def make_key_simple(r):
    return (
        (r.get('Prop Firm') or '').strip(),
        (r.get('Date Purchased') or '').strip(),
        (r.get('Account Size') or '').strip(),
        (r.get('Status') or '').strip(),
        (r.get('Phase') or '').strip(),
        (r.get('Eval #') or '').strip(),
    )

# Check uniqueness in DB
db_keys = [make_key_simple(ev) for ev in db_evals]
db_key_counts = Counter(db_keys)
non_unique_db = {k: c for k, c in db_key_counts.items() if c > 1}
print(f'\n=== DB key uniqueness (firm,date,size,status,phase,eval#) ===')
print(f'Unique keys: {len(db_key_counts)}')
print(f'Non-unique keys: {len(non_unique_db)} covering {sum(non_unique_db.values())} rows')
if non_unique_db:
    for k, c in list(non_unique_db.items())[:5]:
        print(f'  {k}: {c}x')
