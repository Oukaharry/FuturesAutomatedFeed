import csv, json

# Check the fixed CSV for prop firm / account mismatches
with open(r'C:\Users\harry\Downloads\Chris_evaluations_fixed.csv', 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

# Also check what's currently in the DB
import sqlite3
db = sqlite3.connect('dashboard/dashboard.db')
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])
db.close()

PREFIX_TO_FIRM = {
    'FNFT': 'FundedNext',
    'MFFU': 'My Funded Futures',
    'V2': 'Topstep',
    'APX': 'Apex',
}

def check_mismatches(label, data):
    mismatches = []
    for i, row in enumerate(data):
        firm = (row.get('Prop Firm') or '').strip()
        acct = (row.get('Account #') or '').strip()
        acct1 = (row.get('Account #.1') or '').strip()
        for col_name, val in [('Account #', acct), ('Account #.1', acct1)]:
            if not val or not firm:
                continue
            for prefix, expected_firm in PREFIX_TO_FIRM.items():
                if val.upper().startswith(prefix + '-') or val.upper().startswith(prefix + '_'):
                    if expected_firm != firm:
                        mismatches.append((i+1, firm, col_name, val, expected_firm))
                    break
    print(f'\n{label}: {len(data)} rows, {len(mismatches)} mismatches')
    for idx, firm, col, acct, expected in mismatches[:40]:
        print(f'  Row {idx}: Firm="{firm}"  {col}="{acct}"  -> should be "{expected}"')
    if len(mismatches) > 40:
        print(f'  ...and {len(mismatches) - 40} more')
    return mismatches

csv_mm = check_mismatches('Fixed CSV', rows)
db_mm = check_mismatches('DB (current)', db_evals)

# Check where these came from - look at the original extraction JSON
with open('_chris_ream_extracted.json', 'r') as f:
    extracted = json.load(f)

# Check account_maps for these mismatched rows
print('\n--- Checking account_maps for mismatched rows ---')
account_maps = extracted.get('account_maps', {})
for idx, firm, col, acct, expected in db_mm[:15]:
    row_key = str(idx - 1)  # 0-indexed
    maps = account_maps.get(row_key, [])
    print(f'  Row {idx} (Firm={firm}): account_maps={maps}')
