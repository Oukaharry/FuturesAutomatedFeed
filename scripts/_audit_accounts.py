"""Comprehensive audit of Chris's account numbers - current state."""
import json, sqlite3
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Total evaluations: {len(evals)}')

# Categorize every row
missing_acct = []       # No Account #
missing_acct1 = []      # No Account #.1
missing_both = []       # No Account # AND no Account #.1
has_acct = 0
has_acct1 = 0
has_either = 0
total_ip = 0

for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    size = (ev.get('Account Size') or '').strip()
    
    if status == 'In Progress':
        total_ip += 1
    
    if a:
        has_acct += 1
    else:
        missing_acct.append(i)
    
    if a1:
        has_acct1 += 1
    else:
        missing_acct1.append(i)
    
    if a or a1:
        has_either += 1
    else:
        missing_both.append(i)

print(f'\nAccount # filled: {has_acct}/{len(evals)} ({100*has_acct/len(evals):.1f}%)')
print(f'Account #.1 filled: {has_acct1}/{len(evals)} ({100*has_acct1/len(evals):.1f}%)')
print(f'Has either: {has_either}/{len(evals)} ({100*has_either/len(evals):.1f}%)')
print(f'Missing both: {len(missing_both)}/{len(evals)} ({100*len(missing_both)/len(evals):.1f}%)')
print(f'In Progress rows: {total_ip}')

# Detail missing both
print(f'\n=== Rows missing BOTH accounts ({len(missing_both)}) ===')
for i in missing_both:
    ev = evals[i]
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    size = (ev.get('Account Size') or '').strip()
    print(f'  Row {i:>3}: Firm={firm:<22} Status={status:<14} Size={size:<12} Date={purchased}')

# Detail missing Account # only (has Account #.1)
print(f'\n=== Rows missing Account # but HAS Account #.1 ({len(missing_acct) - len(missing_both)}) ===')
for i in missing_acct:
    if i in missing_both:
        continue
    ev = evals[i]
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    print(f'  Row {i:>3}: Firm={firm:<22} Status={status:<14} Acct#.1={a1:<16} Date={purchased}')

# Detail missing Account #.1 only (has Account #)  
print(f'\n=== Rows missing Account #.1 but HAS Account # ({len(missing_acct1) - len(missing_both)}) ===')
for i in missing_acct1:
    if i in missing_both:
        continue
    ev = evals[i]
    a = (ev.get('Account #') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    print(f'  Row {i:>3}: Firm={firm:<22} Status={status:<14} Acct#={a:<16} Date={purchased}')

# Firm breakdown of missing
print(f'\n=== Firm breakdown of missing Account # ===')
firms_missing = Counter()
for i in missing_acct:
    firm = (evals[i].get('Prop Firm') or '').strip()
    firms_missing[firm] += 1
for f, c in firms_missing.most_common():
    print(f'  {f}: {c}')

print(f'\n=== Firm breakdown of missing Account #.1 ===')
firms_missing1 = Counter()
for i in missing_acct1:
    firm = (evals[i].get('Prop Firm') or '').strip()
    firms_missing1[firm] += 1
for f, c in firms_missing1.most_common():
    print(f'  {f}: {c}')
