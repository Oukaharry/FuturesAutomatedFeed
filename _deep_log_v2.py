"""Deep log re-extraction V2 - comprehensive but focused.
Extracts ALL [MATCHED EVAL] and [SESSION] data from logs,
then builds the best firm-filtered account for each row.
Clears corrupted accounts and fills missing ones."""
import json, re, os, glob, sqlite3, csv
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOGS_DIR = 'logs'

# Load current evals
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Loaded {len(evals)} evaluations')

# Known firm prefixes
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

# Valid account format
VALID_ACCT = re.compile(r'^[A-Z]{2,5}-[A-Z0-9]{3,6}$')

# Corrupted patterns
CORRUPTED_PATTERNS = [
    re.compile(r'FTPROPLUS'),
    re.compile(r'CHCHRISREAM'),
    re.compile(r'FNFTFA'),
    re.compile(r'MFFU(EV|SF)(STP|SCL|FLX|CRFLX|RPD)'),
    re.compile(r'TDFYSL'),
    re.compile(r'50KTC-V2'),
    re.compile(r'EXPRESS-V2'),
    re.compile(r'^ELTD[A-Z]{2}\d{10,}'),
    re.compile(r'AFAD(QAS|VEV)'),
    re.compile(r'FNFT-FNFT'),
    re.compile(r'MFFU-MFFU'),
    re.compile(r'TDFY-FTDF'),
    re.compile(r'TDFY-MFFU'),
    re.compile(r'MFFU-FNFT'),
    re.compile(r'MFFU-TDFYSL'),
    re.compile(r'V2-FNFT'),
    re.compile(r'V2-MFFU'),
    re.compile(r'V2-TDFYSL'),
    re.compile(r'TDF-FNFT'),
    re.compile(r'TDF-MFFU'),
    re.compile(r'TDF-TDFYSL'),
    re.compile(r'FNFT-MFFU'),
    re.compile(r'FNFT-TDFYSL'),
    re.compile(r'AFAD-MFFU'),
    re.compile(r'TDFY-FNFT'),
]

def is_corrupted(val):
    if not val:
        return False
    for pat in CORRUPTED_PATTERNS:
        if pat.search(val):
            return True
    return False

def is_valid_account(val):
    if not val:
        return False
    return bool(VALID_ACCT.match(val)) and not is_corrupted(val)

# ============ PHASE 1: Extract from logs ============
log_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'www.tradeopss.com.error.log.*')))
print(f'Found {len(log_files)} log files')

MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')

row_to_raw = defaultdict(list)  # eval_idx -> [(raw_acct, phase)]
all_session_accounts = set()

total_matched = 0
total_session = 0

for logfile in log_files:
    fname = os.path.basename(logfile)
    mc = 0
    sc = 0
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = MATCHED_EVAL_RE.search(line)
            if m:
                idx = int(m.group(1))
                acct = m.group(2)
                phase = m.group(3)
                row_to_raw[idx].append((acct, phase))
                mc += 1
                continue
            
            m = SESSION_RE.search(line)
            if m:
                acct_guess = m.group(1)
                if VALID_ACCT.match(acct_guess):
                    all_session_accounts.add(acct_guess)
                    sc += 1
    total_matched += mc
    total_session += sc
    print(f'  {fname}: {mc:>7} matched_eval, {sc:>7} session')

print(f'\nTotal: {total_matched} [MATCHED EVAL], {total_session} [SESSION]')
print(f'Unique rows with matches: {len(row_to_raw)}')
print(f'Unique session accounts: {len(all_session_accounts)}')

# Also load from original extraction
with open('_chris_ream_extracted.json', 'r') as f:
    extracted = json.load(f)

for sa in extracted.get('session_accounts', []):
    if isinstance(sa, str) and VALID_ACCT.match(sa):
        all_session_accounts.add(sa)

print(f'Session accounts (with original): {len(all_session_accounts)}')

# Build raw_number -> prefixed versions map
raw_to_prefixed = defaultdict(set)
for sa in all_session_accounts:
    if '-' in sa:
        prefix, num = sa.split('-', 1)
        raw_to_prefixed[num].add(sa)

# ============ PHASE 2: For each row, pick best firm-matching account ============
print(f'\n=== Building best accounts per row ===')

changes = []  # (row_idx, field, old_val, new_val)

for idx in range(len(evals)):
    ev = evals[idx]
    firm = (ev.get('Prop Firm') or '').strip()
    expected_prefix = FIRM_TO_PREFIX.get(firm, '')
    if not expected_prefix:
        continue
    
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    
    a_corrupted = is_corrupted(a)
    a1_corrupted = is_corrupted(a1)
    a_valid = is_valid_account(a) and a.startswith(expected_prefix + '-')
    a1_valid = is_valid_account(a1) and a1.startswith(expected_prefix + '-')
    
    needs_acct = not a_valid  # empty, corrupted, or wrong prefix
    needs_acct1 = not a1_valid
    
    if not needs_acct and not needs_acct1:
        continue  # Both are valid
    
    # Collect ALL firm-matching candidates from logs
    candidates = set()
    
    # From [MATCHED EVAL]
    for raw_acct, phase in row_to_raw.get(idx, []):
        if VALID_ACCT.match(raw_acct) and raw_acct.startswith(expected_prefix + '-'):
            candidates.add(raw_acct)
        elif raw_acct in raw_to_prefixed:
            for prefixed in raw_to_prefixed[raw_acct]:
                if prefixed.startswith(expected_prefix + '-'):
                    candidates.add(prefixed)
    
    # From account_maps  
    for acct in extracted.get('account_maps', {}).get(str(idx), []):
        if isinstance(acct, str) and VALID_ACCT.match(acct) and acct.startswith(expected_prefix + '-'):
            candidates.add(acct)
    
    if not candidates:
        continue
    
    # Sort candidates and pick distinct ones for Account # and Account #.1
    sorted_cands = sorted(candidates)
    
    # Keep existing valid values
    current_valid = set()
    if a_valid:
        current_valid.add(a)
    if a1_valid:
        current_valid.add(a1)
    
    # Available candidates (excluding already-used ones)
    available = [c for c in sorted_cands if c not in current_valid]
    
    if needs_acct and available:
        new_a = available[0]
        changes.append((idx, 'Account #', a, new_a))
        current_valid.add(new_a)
        available = [c for c in available if c != new_a]
    
    if needs_acct1 and available:
        new_a1 = available[0]
        changes.append((idx, 'Account #.1', a1, new_a1))
    elif needs_acct1 and not available and needs_acct:
        # Both needed but only one candidate - use it for Account #
        pass

print(f'Changes to make: {len(changes)}')

# Categorize changes
clears = sum(1 for _, _, old, new in changes if is_corrupted(old))
fills = sum(1 for _, _, old, new in changes if not old)
replaces = sum(1 for _, _, old, new in changes if old and not is_corrupted(old))
acct_changes = sum(1 for _, f, _, _ in changes if f == 'Account #')
acct1_changes = sum(1 for _, f, _, _ in changes if f == 'Account #.1')

print(f'  Clearing corrupted: {clears}')
print(f'  Filling empty: {fills}')
print(f'  Replacing invalid: {replaces}')
print(f'  Account # changes: {acct_changes}')
print(f'  Account #.1 changes: {acct1_changes}')

# Show some examples
print(f'\n=== Sample changes ===')
for idx, field, old, new in changes[:20]:
    firm = (evals[idx].get('Prop Firm') or '').strip()
    print(f'  Row {idx:>3} {field:<12}: {old[:35]:<37} -> {new:<16} ({firm})')

# ============ PHASE 3: Also clear any remaining corrupted that we CAN'T replace ============
clear_only = []
for idx in range(len(evals)):
    ev = evals[idx]
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if is_corrupted(val):
            # Check if we already have a change for this
            already_changed = any(c[0] == idx and c[1] == field for c in changes)
            if not already_changed:
                clear_only.append((idx, field, val))

print(f'\nCorrupted values to clear (no replacement found): {len(clear_only)}')
for idx, field, val in clear_only[:20]:
    firm = (evals[idx].get('Prop Firm') or '').strip()
    print(f'  Row {idx:>3} {field:<12}: {val[:40]:<42} ({firm})')

# ============ PHASE 4: Apply all changes ============
print(f'\n=== Applying changes ===')

for idx, field, old, new in changes:
    evals[idx][field] = new

for idx, field, val in clear_only:
    evals[idx][field] = ''

# Count final state
has_acct = sum(1 for ev in evals if is_valid_account((ev.get('Account #') or '').strip()))
has_acct1 = sum(1 for ev in evals if is_valid_account((ev.get('Account #.1') or '').strip()))
has_either = sum(1 for ev in evals 
    if is_valid_account((ev.get('Account #') or '').strip()) 
    or is_valid_account((ev.get('Account #.1') or '').strip()))
missing_both = len(evals) - has_either
still_corrupted = sum(1 for ev in evals 
    for f in ['Account #', 'Account #.1'] 
    if is_corrupted((ev.get(f) or '').strip()))

print(f'Valid Account #: {has_acct}/{len(evals)} ({100*has_acct/len(evals):.1f}%)')
print(f'Valid Account #.1: {has_acct1}/{len(evals)} ({100*has_acct1/len(evals):.1f}%)')
print(f'Has either valid: {has_either}/{len(evals)} ({100*has_either/len(evals):.1f}%)')
print(f'Missing both: {missing_both}/{len(evals)} ({100*missing_both/len(evals):.1f}%)')
print(f'Still corrupted: {still_corrupted}')

# Prefix mismatch check
mismatches = 0
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    prefix = FIRM_TO_PREFIX.get(firm, '')
    if not prefix:
        continue
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if val and '-' in val:
            p = val.split('-')[0]
            if p != prefix and val not in ('', ):
                # Some special cases
                if firm == 'TradeDay' and p == 'ELTD':
                    continue
                mismatches += 1
                # print(f'  Row {i} {field}: {val} prefix={p} expected={prefix} ({firm})')
print(f'Prefix mismatches: {mismatches}')

# Save to DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
            (json.dumps(evals),))
db.commit()
db.close()
print(f'\nDB updated')

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

# Apply same changes to CSV
for idx, field, old, new in changes:
    if idx < len(csv_rows):
        csv_rows[idx][field] = new

for idx, field, val in clear_only:
    if idx < len(csv_rows):
        csv_rows[idx][field] = ''

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

print(f'CSV updated: {CSV_PATH}')

# List remaining missing-both rows
print(f'\n=== Remaining rows missing both accounts ===')
still_missing = []
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    a_ok = is_valid_account(a)
    a1_ok = is_valid_account(a1)
    if not a_ok and not a1_ok:
        firm = (ev.get('Prop Firm') or '').strip()
        status = (ev.get('Status P1') or '').strip()
        purchased = (ev.get('Date Purchased') or '').strip()
        still_missing.append(i)
        print(f'  Row {i:>3}: Firm={firm:<22} Status={status:<14} Date={purchased}')

print(f'\nTotal still missing both: {len(still_missing)}')
