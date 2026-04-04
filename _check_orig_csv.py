"""Check original Chris_evaluations.csv and compare with current DB/fixed CSV."""
import csv, json, sqlite3

ORIG_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
FIXED_CSV = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
DB_PATH = 'dashboard/dashboard.db'

# Read original
with open(ORIG_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    orig_fields = reader.fieldnames
    orig_rows = list(reader)

# Read fixed
with open(FIXED_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fixed_fields = reader.fieldnames
    fixed_rows = list(reader)

# Read DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Original CSV: {len(orig_rows)} rows, {len(orig_fields)} cols')
print(f'Fixed CSV:    {len(fixed_rows)} rows, {len(fixed_fields)} cols')
print(f'DB:           {len(db_evals)} evals')

# Count accounts
for name, rows in [('Original', orig_rows), ('Fixed', fixed_rows)]:
    a = sum(1 for r in rows if (r.get('Account #') or '').strip())
    a1 = sum(1 for r in rows if (r.get('Account #.1') or '').strip())
    both = sum(1 for r in rows if (r.get('Account #') or '').strip() and (r.get('Account #.1') or '').strip())
    neither = sum(1 for r in rows if not (r.get('Account #') or '').strip() and not (r.get('Account #.1') or '').strip())
    print(f'\n{name}: Acct#={a}, Acct#.1={a1}, both={both}, neither={neither}')

# Check if original is corrupted or clean
print(f'\n=== Checking original CSV for issues ===')
# Check for duplicate rows (this was the big issue before)
from collections import Counter
def make_key(r):
    return (
        (r.get('Prop Firm') or '').strip(),
        (r.get('Date Purchased') or '').strip(),
        (r.get('Eval #') or '').strip(),
        (r.get('Account Size') or '').strip(),
    )

keys = [make_key(r) for r in orig_rows]
dupes = {k: c for k, c in Counter(keys).items() if c > 1}
print(f'Duplicate keys: {len(dupes)}')
if dupes:
    for k, c in list(dupes.items())[:5]:
        print(f'  {k}: {c}x')

# Check column alignment 
print(f'\nColumns match: orig={len(orig_fields)} vs fixed={len(fixed_fields)}')
if orig_fields != fixed_fields:
    missing_in_fixed = set(orig_fields) - set(fixed_fields)
    missing_in_orig = set(fixed_fields) - set(orig_fields)
    if missing_in_fixed:
        print(f'  Missing in fixed: {missing_in_fixed}')
    if missing_in_orig:
        print(f'  Missing in original: {missing_in_orig}')

# Show sample accounts from orig to see the formats
print(f'\n=== Sample original accounts (first 30 non-empty) ===')
shown = 0
for i, r in enumerate(orig_rows):
    a = (r.get('Account #') or '').strip()
    a1 = (r.get('Account #.1') or '').strip()
    if (a or a1) and shown < 30:
        firm = (r.get('Prop Firm') or '').strip()
        print(f'  Row {i:>3}: {firm:<22} A={a!r:<45} A.1={a1!r}')
        shown += 1

# Check for the 7 TradeDay In Progress rows
print(f'\n=== TradeDay rows in original ===')
td_count = 0
for i, r in enumerate(orig_rows):
    firm = (r.get('Prop Firm') or '').strip()
    if firm == 'TradeDay':
        phase = (r.get('Phase') or '').strip()
        status = (r.get('Status') or '').strip()
        if status == 'In Progress' or phase == 'In Progress':
            td_count += 1
            print(f'  Row {i}: Phase={phase!r} Status={status!r}')
print(f'TradeDay In Progress count: {td_count}')
