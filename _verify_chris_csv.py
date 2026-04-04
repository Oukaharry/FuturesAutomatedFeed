import csv

with open(r'_chris_ream_full.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = [r for r in reader if r.get('Row #', '').strip() and '---' not in r.get('Row #', '')]

print(f'Total data rows: {len(rows)}')
has_acct = sum(1 for r in rows if r.get('Account #','').strip())
has_acct1 = sum(1 for r in rows if r.get('Account #.1','').strip())
has_hr1 = sum(1 for r in rows if r.get('Hedge Result 1','').strip())
has_hr11 = sum(1 for r in rows if r.get('Hedge Result 1.1','').strip())
has_firm = sum(1 for r in rows if r.get('Prop Firm','').strip())
has_farm = sum(1 for r in rows if r.get('Hedge Day 1','').strip())
has_hnet = sum(1 for r in rows if r.get('Hedge Net','').strip())
has_hnet1 = sum(1 for r in rows if r.get('Hedge Net.1','').strip())
has_any = sum(1 for r in rows if any(v.strip() for k,v in r.items() if k != 'Row #'))

print(f'Account #:         {has_acct}')
print(f'Account #.1:       {has_acct1}')
print(f'Hedge Result 1:    {has_hr1}')
print(f'Hedge Result 1.1:  {has_hr11}')
print(f'Hedge Net:         {has_hnet}')
print(f'Hedge Net.1:       {has_hnet1}')
print(f'Prop Firm:         {has_firm}')
print(f'Hedge Day 1:       {has_farm}')
print(f'Rows with any data:{has_any}')
print(f'Empty rows:        {len(rows) - has_any}')

# Show sample rows with hedge result data
print('\n=== SAMPLE ROWS WITH EVAL HEDGE RESULTS ===')
count = 0
for r in rows:
    hr1 = r.get('Hedge Result 1','').strip()
    if hr1:
        acct = r.get('Account #','').strip()
        firm = r.get('Prop Firm','').strip()
        hnet = r.get('Hedge Net','').strip()
        print(f"  Row {r['Row #']:>3}  Acct={acct:25s}  Firm={firm:20s}  HR1={hr1:>10s}  Net={hnet:>10s}")
        count += 1
        if count >= 15:
            break

# Show sample rows with funded hedge results
print('\n=== SAMPLE ROWS WITH FUNDED HEDGE RESULTS ===')
count = 0
for r in rows:
    hr11 = r.get('Hedge Result 1.1','').strip()
    if hr11:
        acct1 = r.get('Account #.1','').strip()
        firm = r.get('Prop Firm','').strip()
        hnet1 = r.get('Hedge Net.1','').strip()
        print(f"  Row {r['Row #']:>3}  Acct.1={acct1:25s}  Firm={firm:20s}  HR1.1={hr11:>10s}  Net.1={hnet1:>10s}")
        count += 1
        if count >= 15:
            break

# Show sample rows with farming data
print('\n=== SAMPLE ROWS WITH FARMING DATA ===')
count = 0
for r in rows:
    hd1 = r.get('Hedge Day 1','').strip()
    if hd1:
        acct1 = r.get('Account #.1','').strip() or r.get('Account #','').strip()
        print(f"  Row {r['Row #']:>3}  Acct={acct1:25s}  HD1={hd1:>10s}  HD2={r.get('Hedge Day 2',''):>10s}  HD3={r.get('Hedge Day 3',''):>10s}")
        count += 1
        if count >= 15:
            break

# Firm breakdown
print('\n=== PROP FIRM BREAKDOWN ===')
firms = {}
for r in rows:
    firm = r.get('Prop Firm','').strip()
    if firm:
        firms[firm] = firms.get(firm, 0) + 1
for firm, cnt in sorted(firms.items(), key=lambda x: -x[1]):
    print(f"  {firm:25s}: {cnt}")
