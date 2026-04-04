"""Deep log re-extraction for Chris Ream.
Previous extraction only used [MATCHED EVAL] lines. This one also uses:
1. [SESSION] account_guess lines
2. FINAL DATA TO SAVE blocks
3. Dashboard Account lines  
4. account_maps from the original extracted JSON
5. Cross-reference eval_idx to get firm-filtered BEST account per row
"""
import json, re, os, glob
from collections import defaultdict, Counter

LOGS_DIR = 'logs'
log_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'www.tradeopss.com.error.log.*')))
print(f'Found {len(log_files)} log files')

# Load existing extraction data
with open('_chris_ream_extracted.json', 'r') as f:
    extracted = json.load(f)

with open('_log_account_fixes.json', 'r') as f:
    log_fixes = json.load(f)

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
    'Blue Sky': 'BLSKY',
    'The Funded Trader': 'TFT',
}

PREFIX_TO_FIRM = {}
for firm, prefix in FIRM_TO_PREFIX.items():
    PREFIX_TO_FIRM[prefix] = firm

# Valid account pattern
VALID_ACCT = re.compile(r'^[A-Z]{2,5}-[A-Z0-9]{3,6}$')

# Patterns to search in logs
# 1. [MATCHED EVAL] eval_idx=N account=X phase=Y num=Z drift=D
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')

# 2. [SESSION] account_guess=PREFIX-XXXXX best_phase=Y
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')

# 3. FINAL DATA TO SAVE blocks - look for eval_idx and account in the JSON-like data
FINAL_DATA_RE = re.compile(r'FINAL DATA TO SAVE')

# 4. Dashboard Account: XXXX
DASHBOARD_ACCT_RE = re.compile(r'Dashboard Account:\s*(\S+)')

# 5. "eval_idx": N ... "Account #": "XXXX"
EVAL_IDX_LINE_RE = re.compile(r'"eval_idx":\s*(\d+)')
ACCT_LINE_RE = re.compile(r'"Account #":\s*"([^"]*)"')
ACCT1_LINE_RE = re.compile(r'"Account #\.1":\s*"([^"]*)"')

# Build comprehensive row-to-accounts mapping
row_to_matched = defaultdict(list)  # eval_idx -> [(full_acct, phase)]
all_session_accounts = set()        # All SESSION account_guess values
row_to_final_data = defaultdict(dict)  # eval_idx -> {acct, acct1} from FINAL DATA blocks

total_matched = 0
total_session = 0 
total_final = 0

for logfile in log_files:
    fname = os.path.basename(logfile)
    matched_count = 0
    session_count = 0
    
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        in_final_data = False
        final_data_lines = []
        
        for line in f:
            # [MATCHED EVAL] lines
            m = MATCHED_EVAL_RE.search(line)
            if m:
                idx, acct, phase = int(m.group(1)), m.group(2), m.group(3)
                # Build full account with prefix from SESSION context
                row_to_matched[idx].append((acct, phase))
                matched_count += 1
                continue
            
            # [SESSION] lines
            m = SESSION_RE.search(line)
            if m:
                acct_guess = m.group(1)
                if VALID_ACCT.match(acct_guess):
                    all_session_accounts.add(acct_guess)
                    session_count += 1
                continue
            
            # FINAL DATA TO SAVE blocks
            if 'FINAL DATA TO SAVE' in line:
                in_final_data = True
                final_data_lines = []
                continue
            
            if in_final_data:
                final_data_lines.append(line)
                # Look for eval_idx and account in this block
                m_idx = EVAL_IDX_LINE_RE.search(line)
                if m_idx:
                    current_eval_idx = int(m_idx.group(1))
                
                m_acct = ACCT_LINE_RE.search(line)
                if m_acct and not ACCT1_LINE_RE.search(line):
                    val = m_acct.group(1).strip()
                    if val and VALID_ACCT.match(val):
                        if 'current_eval_idx' in dir():
                            row_to_final_data[current_eval_idx]['Account #'] = val
                            total_final += 1
                
                m_acct1 = ACCT1_LINE_RE.search(line)
                if m_acct1:
                    val = m_acct1.group(1).strip()
                    if val and VALID_ACCT.match(val):
                        if 'current_eval_idx' in dir():
                            row_to_final_data[current_eval_idx]['Account #.1'] = val
                            total_final += 1
                
                # End of block after closing brace or empty line
                if line.strip() == '' or (line.strip() == '}' and len(final_data_lines) > 3):
                    in_final_data = False
    
    total_matched += matched_count
    total_session += session_count
    print(f'  {fname}: {matched_count} matched_eval, {session_count} session')

print(f'\nTotal: {total_matched} [MATCHED EVAL], {total_session} [SESSION], {total_final} FINAL DATA accounts')
print(f'Unique session accounts: {len(all_session_accounts)}')
print(f'Rows with [MATCHED EVAL]: {len(row_to_matched)}')
print(f'Rows with FINAL DATA accounts: {len(row_to_final_data)}')

# Now build the BEST account for each eval_idx
# For each row, prefer accounts where the prefix matches the firm
import sqlite3
DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'\n=== Building best account per row ===')

# Collect all valid accounts per row from [MATCHED EVAL]
# These are raw numbers - we need to match against session_accounts to get prefixed versions
# First build a map of raw_number -> [PREFIX-number, ...]
raw_to_prefixed = defaultdict(set)
for sa in all_session_accounts:
    if '-' in sa:
        prefix, num = sa.split('-', 1)
        raw_to_prefixed[num].add(sa)

# Also add from the original extracted session_accounts
for sa in extracted.get('session_accounts', []):
    if isinstance(sa, str) and '-' in sa:
        prefix, num = sa.split('-', 1)
        raw_to_prefixed[num].add(sa)
        all_session_accounts.add(sa)

print(f'Updated session accounts: {len(all_session_accounts)}')
print(f'Raw numbers with prefixed versions: {len(raw_to_prefixed)}')

# For each row, find the best firm-matching account
results = {}  # row_idx -> {'Account #': val, 'Account #.1': val}

for idx in range(len(evals)):
    ev = evals[idx]
    firm = (ev.get('Prop Firm') or '').strip()
    expected_prefix = FIRM_TO_PREFIX.get(firm, '')
    if not expected_prefix:
        continue
    
    # Collect ALL candidate accounts for this row
    candidates = set()
    
    # From [MATCHED EVAL]
    for acct, phase in row_to_matched.get(idx, []):
        # acct might be raw number or prefixed
        if VALID_ACCT.match(acct):
            candidates.add(acct)
        elif acct in raw_to_prefixed:
            candidates.update(raw_to_prefixed[acct])
    
    # From FINAL DATA
    fd = row_to_final_data.get(idx, {})
    for field in ['Account #', 'Account #.1']:
        val = fd.get(field, '')
        if val and VALID_ACCT.match(val):
            candidates.add(val)
    
    # From account_maps
    for acct in extracted.get('account_maps', {}).get(str(idx), []):
        if isinstance(acct, str) and VALID_ACCT.match(acct):
            candidates.add(acct)
    
    # Filter to firm-matching accounts only
    firm_accounts = sorted([a for a in candidates if a.startswith(expected_prefix + '-')])
    
    if firm_accounts:
        results[idx] = firm_accounts

# Summarize
print(f'\nRows with firm-matching candidates: {len(results)}')

# Check how many of these fix current issues
fixes_acct = 0
fixes_acct1 = 0
clears_corrupted = 0

for idx, candidates in results.items():
    ev = evals[idx]
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    
    if not a or not VALID_ACCT.match(a):
        fixes_acct += 1
    if not a1 or not VALID_ACCT.match(a1):
        fixes_acct1 += 1

print(f'Would fix Account #: {fixes_acct}')
print(f'Would fix Account #.1: {fixes_acct1}')

# Save detailed results
output = {
    'row_to_matched': {str(k): v for k, v in row_to_matched.items()},
    'row_to_final_data': {str(k): v for k, v in row_to_final_data.items()},
    'session_accounts': sorted(all_session_accounts),
    'results': {str(k): v for k, v in results.items()},
}

with open('_deep_log_results.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f'\nResults saved to _deep_log_results.json')
