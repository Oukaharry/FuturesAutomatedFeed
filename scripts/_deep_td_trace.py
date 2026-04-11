"""Deep dive: v50 has 17 TradeDay rows when v49 had 0. What happened?"""
import json, sqlite3, sys

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get v49 and v50
cur.execute("SELECT version, evaluations FROM data_history WHERE client_id='Chris' AND version IN (49, 50)")
rows = {r[0]: json.loads(r[1]) for r in cur.fetchall()}

v49 = rows[49]
v50 = rows[50]

print(f'v49: {len(v49)} evals, v50: {len(v50)} evals')

# Find which rows changed to TradeDay in v50
print('\n=== Rows that became TradeDay in v50 ===')
for i in range(min(len(v49), len(v50))):
    firm49 = (v49[i].get('Prop Firm') or '').strip()
    firm50 = (v50[i].get('Prop Firm') or '').strip()
    if firm50 == 'TradeDay' and firm49 != 'TradeDay':
        a49 = (v49[i].get('Account #') or '').strip()
        a50 = (v50[i].get('Account #') or '').strip()
        s49 = (v49[i].get('Status P1') or '').strip()
        s50 = (v50[i].get('Status P1') or '').strip()
        print(f'  Row {i}: Firm {firm49!r} -> {firm50!r}  Status={s49}->{s50}  Acct={a49!r}->{a50!r}')

# Any new rows in v50?
if len(v50) > len(v49):
    print(f'\n  v50 has {len(v50)-len(v49)} new rows')

# Check overall Firm distribution in v50
from collections import Counter
firms50 = Counter((ev.get('Prop Firm') or '').strip() for ev in v50)
print('\n=== v50 firm distribution ===')
for f, c in firms50.most_common():
    print(f'  {f}: {c}')

firms49 = Counter((ev.get('Prop Firm') or '').strip() for ev in v49)
print('\n=== v49 firm distribution ===')
for f, c in firms49.most_common():
    print(f'  {f}: {c}')

# Check v51 - the first CSV import
cur.execute("SELECT version, evaluations, change_description FROM data_history WHERE client_id='Chris' AND version=51")
r51 = cur.fetchone()
v51 = json.loads(r51[1])
print(f'\nv51: {len(v51)} evals ({r51[2]})')

# Check what rows 496-658 look like in v51
print('\n=== v51 new rows (496+) - first 20 ===')
for i in range(496, min(520, len(v51))):
    ev = v51[i]
    firm = (ev.get('Prop Firm') or '').strip()
    a = (ev.get('Account #') or '').strip() 
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    print(f'  Row {i}: Firm={firm:<22} Status={status:<14} Acct={a:<30} Date={purchased}')

# Count TD in new rows
print(f'\n=== v51 rows 496+ firm distribution ===')
new_firms = Counter((v51[i].get('Prop Firm') or '').strip() for i in range(496, len(v51)))
for f, c in new_firms.most_common():
    print(f'  {f}: {c}')

db.close()
