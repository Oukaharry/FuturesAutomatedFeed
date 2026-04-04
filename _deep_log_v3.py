"""Phase 2: Try to extract real account numbers from the corrupted values
before they were cleared, and also try broader matching from raw [MATCHED EVAL] numbers.

Strategy:
1. Extract trailing numbers from corrupted patterns (FNFTFACHRISREAM4912 -> 4912)
2. For EXPRESS-V2-432909-XXXXXXXX format, extract the last segment
3. For FTPROPLUSM... and raw Topstep/FTKS numbers, try session account lookup 
4. For rows with [MATCHED EVAL] raw numbers, try ALL possible prefix combos
"""
import json, re, sqlite3, csv, glob, os
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOGS_DIR = 'logs'

# Load current DB state
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

# Load original extracted data (has account_maps and session_accounts)
with open('_chris_ream_extracted.json', 'r') as f:
    extracted = json.load(f)

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

VALID_ACCT = re.compile(r'^[A-Z]{2,5}-[A-Z0-9]{3,6}$')

# Build session account lookups
all_session = set()
for sa in extracted.get('session_accounts', []):
    if isinstance(sa, str) and VALID_ACCT.match(sa):
        all_session.add(sa)

# Also re-scan logs for SESSION accounts (in case the extracted file missed some)
log_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'www.tradeopss.com.error.log.*')))
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')

row_to_raw = defaultdict(list)
for logfile in log_files:
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = SESSION_RE.search(line)
            if m:
                acct = m.group(1)
                if VALID_ACCT.match(acct):
                    all_session.add(acct)
                continue
            m = MATCHED_EVAL_RE.search(line)
            if m:
                idx = int(m.group(1))
                acct = m.group(2)
                phase = m.group(3)
                row_to_raw[idx].append((acct, phase))

print(f'Session accounts: {len(all_session)}')
print(f'Rows with [MATCHED EVAL]: {len(row_to_raw)}')

# Map raw number -> set of prefixed accounts
raw_to_prefixed = defaultdict(set)
for sa in all_session:
    if '-' in sa:
        parts = sa.split('-', 1)
        raw_to_prefixed[parts[1]].add(sa)

# Map prefix -> set of raw numbers (all known accounts for that firm)
prefix_to_raws = defaultdict(set)
for sa in all_session:
    if '-' in sa:
        prefix, num = sa.split('-', 1)
        prefix_to_raws[prefix].add(num)

# Now find all rows that need both accounts
needs_work = []
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    
    a_ok = bool(VALID_ACCT.match(a)) and a.startswith(expected + '-') if a and expected else False
    a1_ok = bool(VALID_ACCT.match(a1)) and a1.startswith(expected + '-') if a1 and expected else False
    
    if not a_ok or not a1_ok:
        needs_work.append((i, firm, expected, a_ok, a1_ok))

print(f'Rows needing work: {len(needs_work)}')

# Strategy: For each row, try to find FIRM-matching accounts from:
# 1. [MATCHED EVAL] raw numbers → session account lookup
# 2. Phase-based filtering (CH=challenge, FA=funded, FD=funded)
# 3. Frequency: pick the most common firm-matching account for that row

changes = []

for row_idx, firm, expected_prefix, has_a, has_a1 in needs_work:
    if not expected_prefix:
        continue
    
    ev = evals[row_idx]
    current_a = (ev.get('Account #') or '').strip() if has_a else ''
    current_a1 = (ev.get('Account #.1') or '').strip() if has_a1 else ''
    
    # Collect all raw numbers from [MATCHED EVAL] for this row
    raw_matches = row_to_raw.get(row_idx, [])
    
    # Build candidate set: firm-matching valid accounts
    candidates = Counter()
    
    for raw_acct, phase in raw_matches:
        # If raw_acct is already a valid prefixed account
        if VALID_ACCT.match(raw_acct) and raw_acct.startswith(expected_prefix + '-'):
            candidates[raw_acct] += 1
            continue
        
        # Try looking up the raw number in session accounts
        if raw_acct in raw_to_prefixed:
            for prefixed in raw_to_prefixed[raw_acct]:
                if prefixed.startswith(expected_prefix + '-'):
                    candidates[prefixed] += 1
        
        # Try constructing PREFIX-raw_acct
        test_acct = f'{expected_prefix}-{raw_acct}'
        if VALID_ACCT.match(test_acct):
            # Verify this account exists in session accounts
            if test_acct in all_session:
                candidates[test_acct] += 1
    
    if not candidates:
        continue
    
    # Pick top candidates (most frequent), excluding current valid ones
    used = set()
    if current_a:
        used.add(current_a)
    if current_a1:
        used.add(current_a1)
    
    sorted_cands = [acct for acct, count in candidates.most_common() if acct not in used]
    
    if not has_a and sorted_cands:
        new_a = sorted_cands[0]
        changes.append((row_idx, 'Account #', ev.get('Account #', ''), new_a))
        used.add(new_a)
        sorted_cands = [a for a in sorted_cands if a != new_a]
    
    if not has_a1 and sorted_cands:
        new_a1 = sorted_cands[0]
        changes.append((row_idx, 'Account #.1', ev.get('Account #.1', ''), new_a1))

print(f'\nAdditional changes found: {len(changes)}')

# Apply changes
for row_idx, field, old, new in changes:
    evals[row_idx][field] = new

# Count final state
def count_valid_accounts(evals_list):
    stats = {'acct': 0, 'acct1': 0, 'either': 0, 'both_missing': 0}
    for ev in evals_list:
        firm = (ev.get('Prop Firm') or '').strip()
        expected = FIRM_TO_PREFIX.get(firm, '')
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        a_ok = bool(VALID_ACCT.match(a)) and (a.startswith(expected + '-') if expected else True) if a else False
        a1_ok = bool(VALID_ACCT.match(a1)) and (a1.startswith(expected + '-') if expected else True) if a1 else False
        if a_ok: stats['acct'] += 1
        if a1_ok: stats['acct1'] += 1
        if a_ok or a1_ok: stats['either'] += 1
        if not a_ok and not a1_ok: stats['both_missing'] += 1
    return stats

stats = count_valid_accounts(evals)
print(f'\nFinal state:')
print(f'  Valid Account #: {stats["acct"]}/{len(evals)} ({100*stats["acct"]/len(evals):.1f}%)')
print(f'  Valid Account #.1: {stats["acct1"]}/{len(evals)} ({100*stats["acct1"]/len(evals):.1f}%)')
print(f'  Has either: {stats["either"]}/{len(evals)} ({100*stats["either"]/len(evals):.1f}%)')
print(f'  Missing both: {stats["both_missing"]}/{len(evals)} ({100*stats["both_missing"]/len(evals):.1f}%)')

# Breakdown of still-missing by firm
missing_firms = Counter()
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and (a.startswith(expected + '-') if expected else True) if a else False
    a1_ok = bool(VALID_ACCT.match(a1)) and (a1.startswith(expected + '-') if expected else True) if a1 else False
    if not a_ok and not a1_ok:
        missing_firms[firm] += 1

print(f'\n  Firm breakdown of missing both:')
for f, c in missing_firms.most_common():
    print(f'    {f}: {c}')

# Check: how many of the missing rows have log data at all?
rows_with_data = 0
rows_no_data = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and (a.startswith(expected + '-') if expected else True) if a else False
    a1_ok = bool(VALID_ACCT.match(a1)) and (a1.startswith(expected + '-') if expected else True) if a1 else False
    if not a_ok and not a1_ok:
        if row_to_raw.get(i):
            rows_with_data += 1
        else:
            rows_no_data += 1

print(f'\n  Missing rows WITH log matches: {rows_with_data}')
print(f'  Missing rows WITHOUT any log matches: {rows_no_data}')

# For rows WITH log data that are still missing, show what accounts they have
print(f'\n=== Missing rows WITH log matches but no firm-matching accounts ===')
shown = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = bool(VALID_ACCT.match(a)) and (a.startswith(expected + '-') if expected else True) if a else False
    a1_ok = bool(VALID_ACCT.match(a1)) and (a1.startswith(expected + '-') if expected else True) if a1 else False
    if not a_ok and not a1_ok and row_to_raw.get(i):
        raw_entries = row_to_raw[i]
        # What prefixes appear?
        raw_counts = Counter()
        for acct, phase in raw_entries:
            if VALID_ACCT.match(acct):
                p = acct.split('-')[0]
                raw_counts[p] += 1
            elif acct in raw_to_prefixed:
                for pa in raw_to_prefixed[acct]:
                    p = pa.split('-')[0]
                    raw_counts[p] += 1
        
        if shown < 30:
            date = (ev.get('Date Purchased') or '').strip()
            top_prefixes = ', '.join(f'{p}:{c}' for p, c in raw_counts.most_common(5))
            print(f'  Row {i:>3}: Firm={firm:<22} Need={expected:<5} Have={top_prefixes}  Date={date}')
            shown += 1

# Save to DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
            (json.dumps(evals),))
db.commit()
db.close()

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

for row_idx, field, old, new in changes:
    if row_idx < len(csv_rows):
        csv_rows[row_idx][field] = new

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

print(f'\nDB and CSV updated')
