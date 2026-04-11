"""Investigate MFFUEVFLX372280271 - where did this account come from?
Row 59 on dashboard = row index ~58 in DB (dashboard is 1-indexed)."""
import json, sqlite3, re

DB_PATH = 'dashboard/dashboard.db'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

# Find the row - dashboard shows row 59, but let's search by the account
target_acct = 'MFFUEVFLX372280271'
found = []
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    if target_acct in a or target_acct in a1:
        firm = (ev.get('Prop Firm') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        status = (ev.get('Status') or '').strip()
        phase = (ev.get('Phase') or '').strip()
        size = (ev.get('Account Size') or '').strip()
        print(f'Row {i}: Firm={firm} Date={date} Size={size} Phase={phase!r} Status={status!r}')
        print(f'  Account #  = {a!r}')
        print(f'  Account #.1= {a1!r}')
        found.append(i)

# Also find ALL rows with date 03/17/2026 and MFF
print(f'\n=== All MFF rows with date 03/17/2026 ===')
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    if firm == 'My Funded Futures' and '03/17/2026' in date or '2026-03-17' in date:
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        status = (ev.get('Status') or '').strip()
        phase = (ev.get('Phase') or '').strip()
        size = (ev.get('Account Size') or '').strip()
        print(f'  Row {i}: Size={size} Phase={phase!r} Status={status!r} A={a!r} A.1={a1!r}')

# Check where MFFUEVFLX format appears across ALL rows
print(f'\n=== All MFFUEVFLX accounts ===')
evflx_rows = []
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    if 'EVFLX' in a or 'EVFLX' in a1:
        firm = (ev.get('Prop Firm') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        print(f'  Row {i}: {firm:<22} {date:12} A={a!r:<35} A.1={a1!r}')
        evflx_rows.append(i)

print(f'Total EVFLX rows: {len(evflx_rows)}')

# Now trace through version history
print(f'\n=== Version history trace for MFFUEVFLX372280271 ===')
cur.execute("SELECT version, evaluations, created_at, change_description FROM data_history WHERE client_id='Chris' ORDER BY version")
versions = cur.fetchall()

for ver, evals_json, ts, desc in versions:
    try:
        ver_evals = json.loads(evals_json)
    except:
        continue
    
    # Search for this account in this version
    for i, ev in enumerate(ver_evals):
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        if target_acct in a or target_acct in a1:
            firm = (ev.get('Prop Firm') or '').strip()
            date = (ev.get('Date Purchased') or '').strip()
            field = 'Account #' if target_acct in a else 'Account #.1'
            print(f'  v{ver} ({ts[:19]}): row {i} {firm} {date} {field}={target_acct}')
            break
    else:
        # Not found in this version
        pass

# Check the original CSV too
import csv
print(f'\n=== Original CSV (Chris_evaluations.csv) ===')
with open(r'c:\Users\harry\Downloads\Chris_evaluations.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        a = (row.get('Account #') or '').strip()
        a1 = (row.get('Account #.1') or '').strip()
        if target_acct in a or target_acct in a1:
            firm = (row.get('Prop Firm') or '').strip()
            date = (row.get('Date Purchased') or '').strip()
            print(f'  Orig row {i}: {firm} {date} A={a!r} A.1={a1!r}')

db.close()
