import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations
from dashboard.app import get_client_data

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1JK1lCkfj8GRQEKD2AOILms8LZom3I5zQ-_UrQU9xw8o/edit?usp=sharing'

# Fetch sheet
result = fetch_evaluations(SHEET_URL)
if isinstance(result, tuple):
    sheet_evals, _ = result
else:
    sheet_evals = result

# Fetch DB
db_data = get_client_data('Josh B.')
db_evals = db_data.get('evaluations', [])

print(f'Sheet rows: {len(sheet_evals)}, DB rows: {len(db_evals)}')

# Check row-by-row differences in Account #
diffs = []
max_rows = max(len(sheet_evals), len(db_evals))
for i in range(max_rows):
    s_acc = str(sheet_evals[i].get('Account #', '') or '').strip() if i < len(sheet_evals) else '<MISSING>'
    d_acc = str(db_evals[i].get('Account #', '') or '').strip() if i < len(db_evals) else '<MISSING>'
    s_acc2 = str(sheet_evals[i].get('Account #.1', '') or '').strip() if i < len(sheet_evals) else '<MISSING>'
    d_acc2 = str(db_evals[i].get('Account #.1', '') or '').strip() if i < len(db_evals) else '<MISSING>'
    
    if s_acc != d_acc or s_acc2 != d_acc2:
        s_pf = sheet_evals[i].get('Prop Firm', '?') if i < len(sheet_evals) else '?'
        d_pf = db_evals[i].get('Prop Firm', '?') if i < len(db_evals) else '?'
        diffs.append(i)
        print(f'Row {i}: SHEET[{s_pf}|{s_acc}|{s_acc2}] vs DB[{d_pf}|{d_acc}|{d_acc2}]')

if not diffs:
    # No row-level diffs - check if accounts are identical
    sheet_accs = set()
    db_accs = set()
    for ev in sheet_evals:
        a1 = str(ev.get('Account #', '') or '').strip()
        a2 = str(ev.get('Account #.1', '') or '').strip()
        if a1: sheet_accs.add(a1)
        if a2: sheet_accs.add(a2)
    for ev in db_evals:
        a1 = str(ev.get('Account #', '') or '').strip()
        a2 = str(ev.get('Account #.1', '') or '').strip()
        if a1: db_accs.add(a1)
        if a2: db_accs.add(a2)
    
    missing = sheet_accs - db_accs
    extra = db_accs - sheet_accs
    print(f'\nAll rows match position-by-position.')
    print(f'Sheet unique accs: {len(sheet_accs)}, DB unique accs: {len(db_accs)}')
    if missing:
        print(f'In sheet not DB: {sorted(missing)}')
    if extra:
        print(f'In DB not sheet: {sorted(extra)}')
    if not missing and not extra:
        print('Account sets are IDENTICAL between sheet and DB.')

print(f'\nTotal row-level differences: {len(diffs)}')

# Also check: are there rows with empty Account # in the DB?
empty_acc_db = [(i, ev.get('Prop Firm','?')) for i, ev in enumerate(db_evals) if not str(ev.get('Account #', '') or '').strip()]
empty_acc_sheet = [(i, ev.get('Prop Firm','?')) for i, ev in enumerate(sheet_evals) if not str(ev.get('Account #', '') or '').strip()]
print(f'\nDB rows with empty Account #: {len(empty_acc_db)}')
for i, pf in empty_acc_db[:20]:
    print(f'  Row {i}: {pf}')
print(f'Sheet rows with empty Account #: {len(empty_acc_sheet)}')
for i, pf in empty_acc_sheet[:20]:
    print(f'  Row {i}: {pf}')
