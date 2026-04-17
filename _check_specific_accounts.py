"""Check specific accounts from dashboard screenshot that are missing Hedge Result 2."""
import sqlite3, json

db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

# Accounts from screenshot (dashboard rows 11-15, "In Progress")
target_accounts = [
    '50KTC-V2-432909-10905509',  # Row 15
    '50KTC-V2-432909-51535151',  # Row 14
    '50KTC-V2-432909-92712421',  # Row 13
    'FNFTCHCHRISREAM93002',       # Row 12
    'FNFTCHCHRISREAM37253',       # Row 11
]

hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

print(f'Looking for {len(target_accounts)} accounts in {len(evals)} evals...\n')

# Search by Account # 
for target in target_accounts:
    found = False
    for i, ev in enumerate(evals):
        acct = str(ev.get('Account #', '')).strip()
        acct1 = str(ev.get('Account #.1', '')).strip()
        if target in acct or target in acct1:
            found = True
            firm = str(ev.get('Prop Firm', '')).strip()
            status = str(ev.get('Status P1', '')).strip()
            print(f'Row {i}: Account={acct}')
            print(f'  Firm: {firm} | Status: {status}')
            print(f'  Account #.1: {acct1}')
            for hc in hedge_cols:
                v = ev.get(hc, '')
                vs = str(v).strip() if v else ''
                marker = '  ✅' if vs and vs != 'nan' else '  ❌ MISSING'
                print(f'  {hc:<25} = {vs or "(empty)"}{marker}')
            
            # Show all fields for context
            print(f'  --- Other key fields ---')
            for key in ['Date Purchased', 'Hedge Result 1', 'Hedge Result 2', 
                        'Hedge Result 3', 'Phase', 'Net P/L 1', 'Net P/L 2']:
                v = str(ev.get(key, '')).strip()
                if v and v != 'nan':
                    print(f'  {key}: {v}')
            print()
    
    if not found:
        print(f'NOT FOUND: {target}\n')

# Also check what the dashboard row numbers correspond to
# Dashboard typically shows newest first (descending), so row 11-15 from bottom
# means these are near the END of the evals list
print(f'\n{"="*80}')
print(f'LAST 20 EVALS (dashboard shows newest first):')
print(f'{"="*80}')
for i in range(max(0, len(evals)-20), len(evals)):
    ev = evals[i]
    acct = str(ev.get('Account #', '')).strip()
    firm = str(ev.get('Prop Firm', '')).strip()
    status = str(ev.get('Status P1', '')).strip()
    hr1 = str(ev.get('Hedge Result 1', '')).strip()
    hr2 = str(ev.get('Hedge Result 2', '')).strip()
    hr11 = str(ev.get('Hedge Result 1.1', '')).strip()
    hr21 = str(ev.get('Hedge Result 2.1', '')).strip()
    print(f'  [{i:>3}] {firm:<20} {status:<15} {acct:<30} HR1={hr1:<12} HR2={hr2:<12} HR1.1={hr11:<12} HR2.1={hr21}')

db.close()
