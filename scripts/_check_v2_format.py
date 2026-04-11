"""Phase 3: Construct PREFIX-number directly from [MATCHED EVAL] raw data.
The problem: V2 (Topstep) and FTKS (Funding Ticks) accounts don't appear in 
[SESSION] lines, so raw_to_prefixed never maps them.

Solution: For each missing row, take the [MATCHED EVAL] raw numbers and 
construct PREFIX-number directly, checking if the format is valid."""
import json, re, sqlite3, csv, glob, os
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOGS_DIR = 'logs'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

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

# First, let's understand the V2 account format
# Check what V2 accounts we currently have (valid ones)
v2_accounts = set()
for ev in evals:
    for f in ['Account #', 'Account #.1']:
        val = (ev.get(f) or '').strip()
        if val.startswith('V2-') and VALID_ACCT.match(val):
            v2_accounts.add(val)
print(f'Existing valid V2 accounts: {len(v2_accounts)}')
for a in sorted(v2_accounts)[:10]:
    print(f'  {a}')

# Check FTKS accounts
ftks_accounts = set()
for ev in evals:
    for f in ['Account #', 'Account #.1']:
        val = (ev.get(f) or '').strip()
        if val.startswith('FTKS-') and VALID_ACCT.match(val):
            ftks_accounts.add(val)
print(f'\nExisting valid FTKS accounts: {len(ftks_accounts)}')

# Check AFAD accounts
afad_accounts = set()
for ev in evals:
    for f in ['Account #', 'Account #.1']:
        val = (ev.get(f) or '').strip()
        if val.startswith('AFAD-') and VALID_ACCT.match(val):
            afad_accounts.add(val)
print(f'Existing valid AFAD accounts: {len(afad_accounts)}')
for a in sorted(afad_accounts):
    print(f'  {a}')

# ====== Check what raw numbers look like in [MATCHED EVAL] for Topstep rows ======
log_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'www.tradeopss.com.error.log.*')))
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')

# Collect raw numbers for specific missing rows
row_to_raw = defaultdict(list)
all_session = set()

for logfile in log_files:
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = MATCHED_EVAL_RE.search(line)
            if m:
                idx = int(m.group(1))
                acct = m.group(2)
                phase = m.group(3)
                row_to_raw[idx].append((acct, phase))
                continue
            m = SESSION_RE.search(line)
            if m:
                all_session.add(m.group(1))

# Check a known Topstep row that HAS an account vs one that doesn't
# Row 15 is Topstep missing, let's look at its raw data
topstep_missing_rows = [15, 16, 18, 31, 32, 33, 43, 56, 62, 63]
topstep_good_rows = []
for i, ev in enumerate(evals):
    if (ev.get('Prop Firm') or '').strip() == 'Topstep':
        a = (ev.get('Account #') or '').strip()
        if VALID_ACCT.match(a) and a.startswith('V2-'):
            topstep_good_rows.append(i)

print(f'\n=== Sample GOOD Topstep row raw data ===')
for i in topstep_good_rows[:3]:
    ev = evals[i]
    a = (ev.get('Account #') or '').strip()
    raw_entries = row_to_raw.get(i, [])
    
    # Show unique raw account formats
    raw_samples = set()
    for acct, phase in raw_entries[:500]:
        raw_samples.add(acct)
    
    print(f'\n  Row {i}: Account #={a}')
    print(f'  Total raw matches: {len(raw_entries)}')
    print(f'  Unique raw accounts (first 30): {sorted(raw_samples)[:30]}')

print(f'\n=== Sample MISSING Topstep row raw data ===')
for i in topstep_missing_rows[:3]:
    raw_entries = row_to_raw.get(i, [])
    raw_samples = set()
    for acct, phase in raw_entries[:500]:
        raw_samples.add(acct)
    
    print(f'\n  Row {i}:')
    print(f'  Total raw matches: {len(raw_entries)}')
    print(f'  Unique raw accounts (first 30): {sorted(raw_samples)[:30]}')

# Check what raw accounts have V2 prefix
print(f'\n=== V2-prefixed raw accounts in logs ===')
v2_raw = set()
for idx, entries in row_to_raw.items():
    for acct, phase in entries:
        if acct.startswith('V2-'):
            v2_raw.add(acct)
print(f'Unique V2-prefixed raw in [MATCHED EVAL]: {len(v2_raw)}')
for a in sorted(v2_raw)[:20]:
    print(f'  {a}')

# Check V2 in session accounts
v2_session = {a for a in all_session if a.startswith('V2-')}
print(f'\nV2 in session accounts: {len(v2_session)}')
for a in sorted(v2_session)[:20]:
    print(f'  {a}')

# Check FTKS in session accounts
ftks_session = {a for a in all_session if a.startswith('FTKS-')}
print(f'\nFTKS in session accounts: {len(ftks_session)}')

# Check AFAD in session accounts
afad_session = {a for a in all_session if a.startswith('AFAD-')}
print(f'\nAFAD in session accounts: {len(afad_session)}')
for a in sorted(afad_session)[:10]:
    print(f'  {a}')
