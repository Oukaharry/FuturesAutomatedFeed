"""Correct approach:
1. Restore v61 state (start of today, already had prior sessions' 493 log accounts)
2. Then only fill EMPTY account slots from logs/history - never overwrite existing values
3. Leave ALL existing non-empty values as-is, regardless of format"""
import json, re, sqlite3, csv, glob, os
from collections import Counter, defaultdict

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOGS_DIR = 'logs'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Step 1: Restore v61 (start of today's session - already has prior fixes)
cur.execute("SELECT evaluations FROM data_history WHERE client_id='Chris' AND version=61")
v61_evals = json.loads(cur.fetchone()[0])
print(f'V61 baseline: {len(v61_evals)} evals')

# Count v61 state
v61_a = sum(1 for ev in v61_evals if (ev.get('Account #') or '').strip())
v61_a1 = sum(1 for ev in v61_evals if (ev.get('Account #.1') or '').strip())
v61_both = sum(1 for ev in v61_evals if (ev.get('Account #') or '').strip() and (ev.get('Account #.1') or '').strip())
v61_neither = sum(1 for ev in v61_evals if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip())
print(f'V61: {v61_a} Acct#, {v61_a1} Acct#.1, {v61_both} both, {v61_neither} neither')

# But v61 has the TradeDay In Progress rows we removed. Check if it's 649 or 656
# v61 says 649 from the version check above, so it already has TD IP removed
# Good - we can use it directly

# Step 2: Scan logs for accounts to fill empty slots
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')

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

# Valid format: PREFIX-number (allow digits in prefix like V2, allow various lengths)
VALID_LOG_ACCT = re.compile(r'^[A-Z][A-Z0-9]{1,4}-[A-Z0-9]{3,6}$')

log_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'www.tradeopss.com.error.log.*')))
row_to_raw = defaultdict(list)
all_session = set()

for logfile in log_files:
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = MATCHED_EVAL_RE.search(line)
            if m:
                row_to_raw[int(m.group(1))].append((m.group(2), m.group(3)))
                continue
            m = SESSION_RE.search(line)
            if m:
                acct = m.group(1)
                if VALID_LOG_ACCT.match(acct):
                    all_session.add(acct)

print(f'Session accounts: {len(all_session)}, Rows with log matches: {len(row_to_raw)}')

raw_to_prefixed = defaultdict(set)
for sa in all_session:
    if '-' in sa:
        _, num = sa.split('-', 1)
        raw_to_prefixed[num].add(sa)

# Step 3: Also scan history for valid accounts
cur.execute("SELECT version, evaluations FROM data_history WHERE client_id='Chris' ORDER BY version")
versions = cur.fetchall()

def make_key(ev):
    firm = (ev.get('Prop Firm') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    eval_num = (ev.get('Eval #') or str(ev.get('eval_num', ''))).strip()
    size = (ev.get('Account Size') or '').strip()
    return (firm, date, eval_num, size)

# Find valid historical accounts (matching firm prefix)
hist_accounts = defaultdict(lambda: {'Account #': None, 'Account #.1': None})
for ver_id, evals_json in versions:
    try:
        ver_evals = json.loads(evals_json)
    except:
        continue
    ver_lookup = defaultdict(list)
    for ev in ver_evals:
        ver_lookup[make_key(ev)].append(ev)
    
    for i, ev in enumerate(v61_evals):
        key = make_key(ev)
        firm = (ev.get('Prop Firm') or '').strip()
        expected = FIRM_TO_PREFIX.get(firm, '')
        for ver_ev in ver_lookup.get(key, []):
            for field in ['Account #', 'Account #.1']:
                val = (ver_ev.get(field) or '').strip()
                if val and expected and val.startswith(expected + '-') and VALID_LOG_ACCT.match(val):
                    hist_accounts[i][field] = val

# Step 4: Fill only EMPTY slots in v61
changes = []
for i, ev in enumerate(v61_evals):
    firm = (ev.get('Prop Firm') or '').strip()
    expected = FIRM_TO_PREFIX.get(firm, '')
    
    for field in ['Account #', 'Account #.1']:
        current_val = (ev.get(field) or '').strip()
        
        # ONLY fill if currently empty
        if current_val:
            continue
        
        # Try history first
        hist_val = hist_accounts.get(i, {}).get(field)
        if hist_val:
            v61_evals[i][field] = hist_val
            changes.append((i, field, '', hist_val, 'history'))
            continue
        
        # Try logs
        if not expected:
            continue
        raw_matches = row_to_raw.get(i, [])
        candidates = Counter()
        for raw_acct, phase in raw_matches:
            if VALID_LOG_ACCT.match(raw_acct) and raw_acct.startswith(expected + '-'):
                candidates[raw_acct] += 1
                continue
            if raw_acct in raw_to_prefixed:
                for prefixed in raw_to_prefixed[raw_acct]:
                    if prefixed.startswith(expected + '-'):
                        candidates[prefixed] += 1
            test = f'{expected}-{raw_acct}'
            if VALID_LOG_ACCT.match(test) and test in all_session:
                candidates[test] += 1
        
        # Pick the most common firm-matching candidate not already used in this row
        other_field = 'Account #.1' if field == 'Account #' else 'Account #'
        other_val = (v61_evals[i].get(other_field) or '').strip()
        
        for acct, count in candidates.most_common():
            if acct != other_val:
                v61_evals[i][field] = acct
                changes.append((i, field, '', acct, 'logs'))
                break

print(f'\nEmpty slots filled: {len(changes)}')
sources = Counter(src for *_, src in changes)
print(f'  From history: {sources.get("history", 0)}')
print(f'  From logs: {sources.get("logs", 0)}')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(v61_evals),))
db.commit()
db.close()

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

# Sync ALL fields from DB to CSV
for i, ev in enumerate(v61_evals):
    if i < len(csv_rows):
        csv_rows[i]['Account #'] = ev.get('Account #', '')
        csv_rows[i]['Account #.1'] = ev.get('Account #.1', '')

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

# Final report
print(f'\n{"="*60}')
print(f'FINAL STATE')
print(f'{"="*60}')
populated_a = sum(1 for ev in v61_evals if (ev.get('Account #') or '').strip())
populated_a1 = sum(1 for ev in v61_evals if (ev.get('Account #.1') or '').strip())
both = sum(1 for ev in v61_evals 
           if (ev.get('Account #') or '').strip() and (ev.get('Account #.1') or '').strip())
neither = sum(1 for ev in v61_evals 
              if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip())
total = len(v61_evals)

print(f'Total: {total}')
print(f'Account # populated: {populated_a}/{total} ({100*populated_a/total:.1f}%)')
print(f'Account #.1 populated: {populated_a1}/{total} ({100*populated_a1/total:.1f}%)')
print(f'Both populated: {both}/{total} ({100*both/total:.1f}%)')
print(f'Neither populated: {neither}/{total} ({100*neither/total:.1f}%)')
print(f'Has at least one: {total-neither}/{total} ({100*(total-neither)/total:.1f}%)')

# Show a few samples of what existed with original formats
print(f'\n=== Existing non-standard format accounts (kept as-is) ===')
shown = 0
for i, ev in enumerate(v61_evals):
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if val and not VALID_LOG_ACCT.match(val) and shown < 20:
            firm = (ev.get('Prop Firm') or '').strip()
            print(f'  Row {i:>3}: {field:12} = {val!r:45} ({firm})')
            shown += 1

print(f'\nDB and CSV updated. Original dashboard formats preserved.')
