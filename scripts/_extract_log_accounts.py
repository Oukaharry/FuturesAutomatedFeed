"""
Extract ALL [MATCHED EVAL] and [SESSION] lines from logs to rebuild row->account mapping.
These lines appear in the server push processing and give us:
  [MATCHED EVAL] eval_idx=89 account=66028 phase=FA num=1 drift=0
  [SESSION] account_guess=MFFU-66028 best_phase=FA ...
"""
import os, glob, re, json, sqlite3
from collections import defaultdict

LOG_DIR = 'logs'
log_files = sorted(glob.glob(os.path.join(LOG_DIR, '*.log.*')))

# Parse [MATCHED EVAL] lines - these directly give row->account  
MATCHED_EVAL_PAT = re.compile(
    r'\[MATCHED EVAL\] eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)\s+num=(\S+)'
)

# Parse [SESSION] lines - these give full account name and phase
SESSION_PAT = re.compile(
    r'\[SESSION\] account_guess=(\S+)\s+best_phase=(\w+)'
)

# Parse hedge result writes
HEDGE_WRITE_PAT = re.compile(
    r'✅ Matched session.*?Column: \[([^\]]+)\] \| Row: (\d+) \| New Value: (.+)'
)

# Parse [FA WRITE] for farming
FA_WRITE_PAT = re.compile(
    r'\[FA WRITE\] Matched acc_num=(\S+) to pre-computed key=(\S+)'
)

# We only care about Chris Ream pushes
# Read ALL log lines, track Chris push blocks

row_to_accounts = defaultdict(set)  # row -> set of (full_account, phase)
session_accounts = set()  # all full accounts seen
found_per_logfile = {}

for log_file in log_files:
    fname = os.path.basename(log_file)
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    in_chris_push = False
    current_session_account = None
    file_matches = 0
    
    for i, line in enumerate(lines):
        # Detect start of Chris push block
        if 'Push for Chris Ream' in line:
            in_chris_push = True
        
        # Detect end of push block (next push for different client, or a REQUEST line for non-Chris)
        if in_chris_push:
            if 'Push for' in line and 'Chris' not in line:
                in_chris_push = False
                continue
            if '[REQUEST] POST /api/client/push' in line:
                # Could be end of push processing
                pass
        
        # [SESSION] lines capture the current session's full account
        sess_match = SESSION_PAT.search(line)
        if sess_match:
            current_session_account = sess_match.group(1)
            session_accounts.add(current_session_account)
        
        # [MATCHED EVAL] lines - THE KEY DATA
        eval_match = MATCHED_EVAL_PAT.search(line)
        if eval_match:
            row_idx = int(eval_match.group(1))
            partial_acct = eval_match.group(2)
            phase = eval_match.group(3)
            
            # Build full account from current_session_account or try resolving
            full_acct = current_session_account if current_session_account else partial_acct
            row_to_accounts[row_idx].add((full_acct, phase))
            file_matches += 1
        
        # Hedge writes
        hedge_match = HEDGE_WRITE_PAT.search(line)
        if hedge_match:
            col = hedge_match.group(1)
            row_idx = int(hedge_match.group(2))
            # This tells us the row is active but doesn't give account directly
    
    if file_matches:
        found_per_logfile[fname] = file_matches

print(f'Log files searched: {len(log_files)}')
print(f'Total session accounts: {len(session_accounts)}')
print(f'Rows with [MATCHED EVAL]: {len(row_to_accounts)}')
print(f'\nMatches per log file:')
for fname, count in sorted(found_per_logfile.items()):
    print(f'  {fname}: {count}')

# Load current DB data
db = sqlite3.connect('dashboard/dashboard.db')
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU', 'Tradeify': 'TDFY', 'Topstep': 'V2',
    'TradeDay': 'TDF', 'FundedNext': 'FNFT', 'Apex Trader Funding': 'APEX',
    'BluSky': 'BLSKY', 'TheFundedTrader': 'TFT', 'Alpha Futures': 'AFAD',
    'Bulenox': 'BLX', 'FastTrackTrading': 'FTT', 'TickTickTrader': 'TTT',
    'Earn2Trade': 'E2T', 'Maverick Trading': 'MAV', 'Elite Trader Funding': 'ETF',
    'Leeloo Trading': 'LELO', 'Funding Ticks': 'FTKS',
}
PREFIX_TO_FIRM = {v: k for k, v in FIRM_TO_PREFIX.items()}

CORRUPTED_PATTERNS = [
    re.compile(r'^MFFU-?MFFU(EVSTP|EVSCL|SFSCL|EVCRFLX|EVFLX)\d+$'),
    re.compile(r'^MFFU(EVSTP|EVSCL|SFSCL|EVCRFLX|EVFLX)\d+$'),
    re.compile(r'^FNFT-?FNFTCH\w+$'),
    re.compile(r'^TDFY-?TDFYSL\d+$'),
    re.compile(r'^50KTC-V2-\d+-\d+$'),
    re.compile(r'^FTPROPLUS\d+$'),
    re.compile(r'^AFAD-?AFADVEV\d+$'),
]

def is_corrupted(val):
    if not val: return False
    val = val.strip()
    for p in CORRUPTED_PATTERNS:
        if p.match(val): return True
    return False

# Check which rows need accounts
needs_fix = {}
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    
    need_a = not a or is_corrupted(a)
    need_a1 = not a1 or is_corrupted(a1)
    
    if need_a or need_a1:
        needs_fix[i] = {'need_a': need_a, 'need_a1': need_a1, 'firm': firm, 'curr_a': a, 'curr_a1': a1}

print(f'\nRows needing fixes: {len(needs_fix)}')

# Match log data to needed rows
can_fix = 0
fixes_to_apply = {}

for row_idx, info in sorted(needs_fix.items()):
    log_data = row_to_accounts.get(row_idx, set())
    if not log_data:
        continue
    
    firm = info['firm']
    exp_prefix = FIRM_TO_PREFIX.get(firm, '')
    
    ch_accounts = []
    fa_accounts = []
    
    for full_acct, phase in log_data:
        # Determine the correct prefix for this account
        acct_prefix = full_acct.split('-')[0] if '-' in full_acct else ''
        
        if phase.upper().startswith('CH'):
            ch_accounts.append(full_acct)
        elif phase.upper() in ('FA', 'FD', 'DD'):
            fa_accounts.append(full_acct)
    
    fix = {}
    if info['need_a'] and ch_accounts:
        # Pick the one matching the firm prefix, or any
        best = None
        for acct in ch_accounts:
            if acct.startswith(exp_prefix + '-'):
                best = acct
                break
        if not best:
            best = ch_accounts[0]
        fix['Account #'] = best
    
    if info['need_a1'] and fa_accounts:
        best = None
        for acct in fa_accounts:
            if acct.startswith(exp_prefix + '-'):
                best = acct
                break
        if not best:
            best = fa_accounts[0]
        fix['Account #.1'] = best
    
    if fix:
        fixes_to_apply[row_idx] = fix
        can_fix += 1

print(f'Rows we can fix from logs: {can_fix}')
print(f'Still unfixable: {len(needs_fix) - can_fix}')

# Show what we found
print(f'\n{"="*100}')
print(f'FIXES TO APPLY:')
for row_idx in sorted(fixes_to_apply.keys())[:50]:
    fix = fixes_to_apply[row_idx]
    info = needs_fix[row_idx]
    parts = []
    if 'Account #' in fix:
        parts.append(f'Acct#={fix["Account #"]}')
    if 'Account #.1' in fix:
        parts.append(f'Acct#.1={fix["Account #.1"]}')
    print(f'  Row {row_idx:>3} [{info["firm"]:<22}] {" | ".join(parts)}')
if len(fixes_to_apply) > 50:
    print(f'  ...and {len(fixes_to_apply) - 50} more')

# Save for the apply step
with open('_log_account_fixes.json', 'w') as f:
    json.dump({
        'fixes': {str(k): v for k, v in fixes_to_apply.items()},
        'session_accounts': sorted(session_accounts),
        'row_to_accounts': {str(k): [(a, p) for a, p in v] for k, v in row_to_accounts.items()},
    }, f, indent=2)
print(f'\nSaved to _log_account_fixes.json')
