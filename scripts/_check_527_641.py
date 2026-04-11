"""Compare row 527 vs row 641 - are they duplicates?"""
import json, sqlite3

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

ev527 = evals[527]
ev641 = evals[641]

print(f'=== Row 527 vs Row 641 field-by-field ===')
all_keys = sorted(set(list(ev527.keys()) + list(ev641.keys())))
same = 0
diff = 0
for k in all_keys:
    v1 = ev527.get(k, '')
    v2 = ev641.get(k, '')
    if v1 == v2:
        same += 1
    else:
        diff += 1
        print(f'  {k:30} 527={str(v1)!r:35} 641={str(v2)!r}')

print(f'\nSame fields: {same}')
print(f'Different fields: {diff}')

# Also check: are there other duplicates in the dataset?
# Look for rows with same (Firm, Date, Account #, Account #.1)
from collections import Counter

def make_acct_key(ev):
    return (
        (ev.get('Prop Firm') or '').strip(),
        (ev.get('Date Purchased') or '').strip(),
        (ev.get('Account #') or '').strip(),
        (ev.get('Account #.1') or '').strip(),
    )

keys = [make_acct_key(ev) for ev in evals]
dupes = {k: c for k, c in Counter(keys).items() if c > 1 and k[2]}  # non-empty acct
print(f'\n=== Duplicate (firm+date+accounts) pairs ===')
for k, c in sorted(dupes.items(), key=lambda x: -x[1]):
    print(f'  {c}x: {k}')

# Show all rows from 03/17/2026
print(f'\n=== ALL rows from 03/17/2026 ===')
for i, ev in enumerate(evals):
    date = (ev.get('Date Purchased') or '').strip()
    if '03/17/2026' in date or '2026-03-17' in date:
        firm = (ev.get('Prop Firm') or '').strip()
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        status = (ev.get('Status') or '').strip()
        phase = (ev.get('Phase') or '').strip()
        size = (ev.get('Account Size') or '').strip()
        print(f'  Row {i}: {firm:<22} Size={size:10} Phase={phase!r:15} Status={status!r:15} A={a!r} A.1={a1!r}')
