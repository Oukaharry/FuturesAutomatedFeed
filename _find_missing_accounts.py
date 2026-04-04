"""Find all missing account numbers in Chris's evaluations and search logs for them."""
import sqlite3, json, os, re, glob

DB_PATH = 'dashboard/dashboard.db'
LOG_DIR = 'logs'

# ── Step 1: Find missing accounts in DB ──
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Total evaluations: {len(evals)}')

missing_both = []
missing_acct = []
missing_acct1 = []

for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    size = (ev.get('Account Size') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    
    if not a and not a1:
        missing_both.append((i, firm, status, size, purchased))
    elif not a:
        missing_acct.append((i, firm, status, size, purchased, a1))
    elif not a1:
        missing_acct1.append((i, firm, status, size, purchased, a))

print(f'\nMissing BOTH Account # and Account #.1: {len(missing_both)}')
print(f'Missing Account # only (has #.1): {len(missing_acct)}')
print(f'Missing Account #.1 only (has #): {len(missing_acct1)}')

print(f'\n{"="*80}')
print(f'ALL rows missing BOTH accounts:')
print(f'{"Row":>5} {"Firm":<22} {"Status":<14} {"Size":<12} {"Date Purchased"}')
print(f'{"-"*5} {"-"*22} {"-"*14} {"-"*12} {"-"*14}')
for idx, firm, status, size, purchased in missing_both:
    print(f'{idx:>5} {firm:<22} {status:<14} {size:<12} {purchased}')

print(f'\n{"="*80}')
print(f'Rows missing Account # (has Account #.1):')
print(f'{"Row":>5} {"Firm":<22} {"Status":<14} {"Size":<12} {"Acct #.1":<18} {"Date Purchased"}')
print(f'{"-"*5} {"-"*22} {"-"*14} {"-"*12} {"-"*18} {"-"*14}')
for idx, firm, status, size, purchased, a1 in missing_acct:
    print(f'{idx:>5} {firm:<22} {status:<14} {size:<12} {a1:<18} {purchased}')

print(f'\n{"="*80}')
print(f'Rows missing Account #.1 (has Account #):')
print(f'{"Row":>5} {"Firm":<22} {"Status":<14} {"Size":<12} {"Acct #":<18} {"Date Purchased"}')
print(f'{"-"*5} {"-"*22} {"-"*14} {"-"*12} {"-"*18} {"-"*14}')
for idx, firm, status, size, purchased, a in missing_acct1:
    print(f'{idx:>5} {firm:<22} {status:<14} {size:<12} {a:<18} {purchased}')

# ── Step 2: Collect all row indices we need to find ──
all_missing_rows = set()
for idx, *_ in missing_both:
    all_missing_rows.add(idx)
for idx, *_ in missing_acct:
    all_missing_rows.add(idx)
for idx, *_ in missing_acct1:
    all_missing_rows.add(idx)

print(f'\n{"="*80}')
print(f'Total rows needing account lookup: {len(all_missing_rows)}')
print(f'Row indices: {sorted(all_missing_rows)}')
