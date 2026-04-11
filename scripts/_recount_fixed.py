"""Recount with fixed VALID_ACCT regex that allows V2 prefix (digit in prefix)."""
import json, re, sqlite3
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'

# FIXED: Allow digits in prefix (V2 has a digit)
VALID_ACCT = re.compile(r'^[A-Z][A-Z0-9]{1,4}-[A-Z0-9]{3,6}$')

FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU',
    'Tradeify': 'TDFY',
    'Topstep': 'V2',
    'TradeDay': 'TDF',
    'FundedNext': 'FNFT',
    'Apex Trader Funding': 'APEX',
    'Funding Ticks': 'FTKS',
    'Alpha Futures': 'AFAD',
}

# Test the regex on known formats
print("=== Regex tests ===")
tests = ['V2-6807', 'MFFU-13045', 'FNFT-R3866', 'TDF-09074', 'TDFY-85817',
         'AFAD-25858', 'APEX-12345', 'FTKS-99999', 'V2-0001',
         'V2-ELTDEN2509080052300', 'MFFU-FNFTFACHRISREAM76807', 'FTPROPLUS338459']
for t in tests:
    print(f'  {t:40} -> {bool(VALID_ACCT.match(t))}')

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

# Count with correct regex
stats = {'ok': 0, 'a_only': 0, 'a1_only': 0, 'missing_both': 0}
missing_firms = Counter()
corrupted = []

for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    
    # Valid = matches regex AND starts with correct firm prefix
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    
    # Check for corrupted (non-empty but doesn't match regex)
    if a and not VALID_ACCT.match(a):
        corrupted.append((i, 'Account #', a, firm))
    if a1 and not VALID_ACCT.match(a1):
        corrupted.append((i, 'Account #.1', a1, firm))
    
    if a_ok and a1_ok:
        stats['ok'] += 1
    elif a_ok:
        stats['a_only'] += 1
    elif a1_ok:
        stats['a1_only'] += 1
    else:
        stats['missing_both'] += 1
        missing_firms[firm] += 1

total = len(evals)
has_either = stats['ok'] + stats['a_only'] + stats['a1_only']

print(f'\n=== CORRECTED COUNTS (fixed V2 regex) ===')
print(f'Total evals: {total}')
print(f'Both valid: {stats["ok"]} ({100*stats["ok"]/total:.1f}%)')
print(f'Missing Account # only: {stats["a_only"]}')
print(f'Missing Account #.1 only: {stats["a1_only"]}')
print(f'Missing BOTH: {stats["missing_both"]} ({100*stats["missing_both"]/total:.1f}%)')
print(f'Coverage (has at least one): {has_either}/{total} ({100*has_either/total:.1f}%)')

if corrupted:
    print(f'\nCorrupted values (non-empty, fails regex): {len(corrupted)}')
    for i, field, val, firm in corrupted[:20]:
        print(f'  Row {i:>3}: {field:12} = {val!r:40} Firm={firm}')

print(f'\nMissing BOTH by firm:')
for f, c in missing_firms.most_common():
    print(f'  {f}: {c}')

# Show some of the still truly missing
print(f'\n=== Sample of truly missing-both rows ===')
shown = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    if not a_ok and not a1_ok and shown < 30:
        phase = (ev.get('Phase') or '').strip()
        status = (ev.get('Status') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        print(f'  Row {i:>3}: {firm:<22} Phase={phase or "empty":10} Status={status or "empty":15} Date={date:12} A={a!r} A1={a1!r}')
        shown += 1
