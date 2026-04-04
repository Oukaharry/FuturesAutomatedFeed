"""
Search ALL server logs for Chris Ream's pushes and extract account numbers per row.
This searches for [SESSION] lines (contain account numbers) and [EVAL_WRITE] lines (contain row assignments).
"""
import re, os, glob, json, sqlite3
from collections import defaultdict

LOG_DIR = 'logs'
CLIENT = 'Chris'

# Load current DB to know which rows need accounts
db = sqlite3.connect('dashboard/dashboard.db')
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT,))
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Total evaluations: {len(evals)}')

# ── Identify all rows missing proper accounts ──
CORRUPTED_PATTERNS = [
    re.compile(r'^MFFU(EVSTP|EVSCL|SFSCL|EVCRFLX|EVFLX)\d+$'),  # MFFU auto-generated
    re.compile(r'^FNFT-?FNFTCH\w+$'),  # FNFT auto-generated
    re.compile(r'^TDFY-?TDFYSL\d+$'),  # TDFY auto-generated
    re.compile(r'^50KTC-V2-\d+-\d+$'),  # Topstep auto-generated
    re.compile(r'^FTPROPLUS\d+$'),  # Funding Ticks auto-generated
    re.compile(r'^AFAD-?AFADVEV\d+$'),  # Alpha Futures auto-generated
]

def is_corrupted(val):
    if not val:
        return False
    val = val.strip()
    for p in CORRUPTED_PATTERNS:
        if p.match(val):
            return True
    return False

needs_acct = set()   # rows missing Account #
needs_acct1 = set()  # rows missing Account #.1

for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    if not a or is_corrupted(a):
        needs_acct.add(i)
    if not a1 or is_corrupted(a1):
        needs_acct1.add(i)

print(f'Rows needing Account #: {len(needs_acct)}')
print(f'Rows needing Account #.1: {len(needs_acct1)}')

# ── Search logs ──
log_files = sorted(glob.glob(os.path.join(LOG_DIR, '*.log.*')))
print(f'\nLog files: {len(log_files)}')

# We need to find lines that mention Chris and contain row/account info
# Key patterns in the logs:
# [SESSION] account=MFFU-09008, client=Chris...
# [EVAL_WRITE] row=XX, col=Account #, val=MFFU-09008...
# Push for Chris: evaluations[XX]['Account #'] = 'MFFU-09008'

# Broader approach: read ALL lines mentioning Chris, capture session accounts and row writes
session_accounts = set()
row_account_writes = defaultdict(dict)  # row -> {field: value}
row_mentions = defaultdict(list)  # row -> [(logfile, line)]

# Patterns
SESSION_PAT = re.compile(r'\[SESSION\].*?account[=:]?\s*([A-Z0-9]+-[A-Z0-9]+)', re.IGNORECASE)
EVAL_WRITE_PAT = re.compile(r"evaluations\[(\d+)\]\[(['\"])(Account #(?:\.1)?)\2\]\s*=\s*['\"]([^'\"]+)['\"]")
ROW_COL_PAT = re.compile(r'row[=: ]+(\d+).*?(Account\s*#(?:\.1)?).*?(?:val|value|=)\s*[\'"]?([A-Z0-9]+-[A-Z0-9]+)', re.IGNORECASE)
HEDGE_ROW_PAT = re.compile(r'(?:hedge|farming).*?row[=: ]+(\d+)', re.IGNORECASE)

# More general: look for "Account #" or account-like numbers near row references
GENERAL_ROW_PAT = re.compile(r'row[=: ]+(\d+)')
ACCOUNT_PAT = re.compile(r'\b([A-Z]{2,5}-[A-Z0-9]{3,10})\b')

chris_lines_count = 0
for log_file in log_files:
    fname = os.path.basename(log_file)
    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except:
        continue
    
    in_chris_block = False
    block_accounts = []
    block_row = None
    
    for line_num, line in enumerate(lines):
        # Check if line mentions Chris
        if 'Chris' not in line and 'chris' not in line.lower():
            if in_chris_block and line.strip():
                # Check if still in a push block
                if not any(x in line for x in ['evaluations[', '[SESSION]', '[EVAL', 'row=', 'Account']):
                    in_chris_block = False
            continue
        
        chris_lines_count += 1
        in_chris_block = True
        
        # Extract session accounts
        sess_match = SESSION_PAT.findall(line)
        for acct in sess_match:
            session_accounts.add(acct)
        
        # Extract eval writes: evaluations[XX]['Account #'] = 'VALUE'
        eval_match = EVAL_WRITE_PAT.findall(line)
        for row, _, field, val in eval_match:
            row_account_writes[int(row)][field] = val
        
        # Extract row + account patterns
        row_col_match = ROW_COL_PAT.findall(line)
        for row, field, val in row_col_match:
            field = field.strip()
            row_account_writes[int(row)][field] = val
        
        # General row mentions with any account-like string
        gen_rows = GENERAL_ROW_PAT.findall(line)
        accts = ACCOUNT_PAT.findall(line)
        for row in gen_rows:
            row_int = int(row)
            if row_int < len(evals) and accts:
                row_mentions[row_int].append((fname, line_num, accts, line.strip()[:200]))

print(f'\nChris-related lines found: {chris_lines_count}')
print(f'Session accounts found: {len(session_accounts)}')
print(f'Direct row->account writes found: {len(row_account_writes)}')
print(f'Rows with account mentions: {len(row_mentions)}')

# ── Also search for the actual push data format used by the MT5 app ──
# The app sends evaluations as JSON array. Look for the data push endpoint logs.
push_data_rows = defaultdict(dict)

for log_file in log_files:
    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except:
        continue
    
    # Find DATA_PUSH blocks for Chris
    # Look for patterns like: "Data push from trader app with N evaluations"
    # and nearby JSON data
    
    # Find all "[PUSH]" or "push" lines with Chris
    for match in re.finditer(r'(?:push|PUSH|DATA_PUSH).*?Chris.*?(?:\n.*?){0,5}', content):
        block = match.group()
        # Try to extract row-level data from the push
        eval_matches = re.findall(r"evaluations\[(\d+)\].*?Account #.*?=\s*'([^']+)'", block)
        for row, acct in eval_matches:
            push_data_rows[int(row)]['Account #'] = acct

print(f'Push data rows extracted: {len(push_data_rows)}')

# ── Now report what we found for each missing row ──
print(f'\n{"="*100}')
print(f'ACCOUNTS FOUND IN LOGS FOR MISSING ROWS:')
print(f'{"="*100}')

found_from_writes = 0
found_from_mentions = 0
results = {}

for i in sorted(needs_acct | needs_acct1):
    ev = evals[i]
    firm = (ev.get('Prop Firm') or '').strip()
    curr_a = (ev.get('Account #') or '').strip()
    curr_a1 = (ev.get('Account #.1') or '').strip()
    
    log_a = row_account_writes.get(i, {}).get('Account #')
    log_a1 = row_account_writes.get(i, {}).get('Account #.1')
    
    # Check mentions for this row
    mentions = row_mentions.get(i, [])
    mention_accts = set()
    for fname, line_num, accts, line_text in mentions:
        for a in accts:
            mention_accts.add(a)
    
    if log_a or log_a1 or mention_accts:
        results[i] = {
            'firm': firm,
            'curr_a': curr_a,
            'curr_a1': curr_a1,
            'log_a': log_a,
            'log_a1': log_a1,
            'mention_accts': list(mention_accts)
        }
        
        if log_a or log_a1:
            found_from_writes += 1
            tag = 'WRITE'
        else:
            found_from_mentions += 1
            tag = 'MENTION'
        
        print(f'  Row {i:>3} [{tag}] Firm={firm:<22}', end='')
        if log_a:
            print(f' Account#={log_a}', end='')
        if log_a1:
            print(f' Account#.1={log_a1}', end='')
        if mention_accts and not log_a and not log_a1:
            print(f' mentioned: {mention_accts}', end='')
        print()

print(f'\nFound from direct writes: {found_from_writes}')
print(f'Found from mentions: {found_from_mentions}')
print(f'Total found: {found_from_writes + found_from_mentions}')
print(f'Still missing: {len(needs_acct | needs_acct1) - found_from_writes - found_from_mentions}')

# Save results for next step
with open('_missing_accounts_from_logs.json', 'w') as f:
    json.dump({
        'session_accounts': sorted(session_accounts),
        'row_account_writes': {str(k): v for k, v in row_account_writes.items()},
        'row_mentions': {str(k): [{'file': fname, 'accts': accts, 'line': line} 
                                   for fname, _, accts, line in v]
                         for k, v in row_mentions.items()},
        'results': results,
        'needs_acct': sorted(needs_acct),
        'needs_acct1': sorted(needs_acct1),
    }, f, indent=2)
print(f'\nSaved to _missing_accounts_from_logs.json')
