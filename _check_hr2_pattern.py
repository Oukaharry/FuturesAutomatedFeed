"""Broader check: How many accounts have HR1+HR3 but are missing HR2?
This would indicate the hedge engine skipped CH2 for these accounts."""
import sqlite3, json
from collections import Counter

db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

# Pattern: Has HR1 and HR3 but missing HR2
has_1_and_3_no_2 = []
has_1_no_2 = []
has_1_no_3 = []

for i, ev in enumerate(evals):
    hr1 = str(ev.get('Hedge Result 1', '')).strip()
    hr2 = str(ev.get('Hedge Result 2', '')).strip()
    hr3 = str(ev.get('Hedge Result 3', '')).strip()
    
    has_hr1 = bool(hr1 and hr1 != 'nan')
    has_hr2 = bool(hr2 and hr2 != 'nan')
    has_hr3 = bool(hr3 and hr3 != 'nan')
    
    if has_hr1 and has_hr3 and not has_hr2:
        firm = str(ev.get('Prop Firm', '')).strip()
        status = str(ev.get('Status P1', '')).strip()
        acct = str(ev.get('Account #', '')).strip()
        has_1_and_3_no_2.append((i, firm, status, acct, hr1, hr3))
    
    if has_hr1 and not has_hr2:
        has_1_no_2.append(i)
    
    if has_hr1 and not has_hr3:
        has_1_no_3.append(i)

print(f'Total evals: {len(evals)}')
print(f'Has HR1 but no HR2: {len(has_1_no_2)}')
print(f'Has HR1 but no HR3: {len(has_1_no_3)}')
print(f'Has HR1 AND HR3 but no HR2: {len(has_1_and_3_no_2)}')

print(f'\n{"="*80}')
print(f'ACCOUNTS WITH HR1+HR3 BUT MISSING HR2 ({len(has_1_and_3_no_2)})')
print(f'{"="*80}')

for i, firm, status, acct, hr1, hr3 in has_1_and_3_no_2:
    print(f'  Row {i:>3} | {firm:<20} | {status:<15} | {acct:<30} | HR1={hr1:<12} HR3={hr3}')

# Check if this is a pattern with specific date ranges
print(f'\n{"="*80}')
print(f'DATE PURCHASED FOR THESE ACCOUNTS')
print(f'{"="*80}')
dates = Counter()
for i, firm, status, acct, hr1, hr3 in has_1_and_3_no_2:
    dp = str(evals[i].get('Date Purchased', '')).strip()
    dates[dp] += 1
    print(f'  Row {i:>3}: Date={dp}')

print(f'\nDate distribution:')
for d, c in dates.most_common():
    print(f'  {d}: {c} accounts')

db.close()
