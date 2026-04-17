"""
Comprehensive Chris Ream log analysis - v2
Captures full push context blocks (not just lines mentioning his name).
A "push block" starts at "Push for Chris Ream" and includes all subsequent
matched session, eval matching, farming, and data-save lines until the next
push or a clear separation.
"""
import re, os, json
from collections import defaultdict, Counter
from datetime import datetime

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# ---- Phase 1: Find push boundaries and extract full blocks ----
# A Chris push block = from "Push for Chris Ream" until next "Push for" (different user) or next major separator

TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
PUSH_START_RE = re.compile(r'Push for Chris Ream: (\d+) deals, balance=([\d.]+), (\d+) evaluations')
PUSH_ANY_RE = re.compile(r'Push for \w')  # Any push (to detect end of Chris block)
SESSION_MATCH_RE = re.compile(r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)')
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s*eval_idx=(\d+)\s+account=(\S+)\s+phase=(\S+)')
FA_RE = re.compile(r'\[FA PRE-COMPUTE\]\s*account=(\S+)\s+farming_days=(\d+)')
FINAL_DATA_RE = re.compile(r'FINAL DATA TO SAVE for Chris Ream')
SAVE_RE = re.compile(r'✅ Data saved for Chris Ream')
PRESERVE_RE = re.compile(r'Preserving (\d+) EXISTING evaluations')
ERROR_RE = re.compile(r'Exception|Traceback|Error', re.IGNORECASE)

# Track pushes and all within-push activity
pushes = []  # List of push dicts

# Stats
total_lines_scanned = 0
total_chris_lines = 0
all_session_matches = []
all_matched_evals = []
all_farming = []
all_errors = []
all_csv_imports = []
eval_count_timeline = []  # (timestamp, eval_count, deal_count, balance, log_file)

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...')
    
    in_chris_block = False
    current_push = None
    lines_since_push = 0
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            total_lines_scanned += 1
            
            # Check for Chris push start
            m = PUSH_START_RE.search(line)
            if m:
                # Save previous push if any
                if current_push:
                    pushes.append(current_push)
                
                ts_m = TS_RE.match(line)
                ts = ts_m.group(1) if ts_m else ''
                
                current_push = {
                    'timestamp': ts,
                    'deals': int(m.group(1)),
                    'balance': float(m.group(2)),
                    'evals': int(m.group(3)),
                    'log': lf,
                    'line': line_num,
                    'session_matches': [],
                    'matched_evals': [],
                    'farming': [],
                    'errors': [],
                    'final_data': False,
                    'data_saved': False,
                    'preserve_count': None,
                }
                in_chris_block = True
                lines_since_push = 0
                total_chris_lines += 1
                
                eval_count_timeline.append((ts, int(m.group(3)), int(m.group(1)), float(m.group(2)), lf))
                continue
            
            # If we're in a Chris block, capture subsequent lines
            if in_chris_block:
                lines_since_push += 1
                
                # End block if we see a push for someone else or 500+ lines
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    if current_push:
                        pushes.append(current_push)
                        current_push = None
                    in_chris_block = False
                    continue
                
                if lines_since_push > 2000:  # Safety limit
                    if current_push:
                        pushes.append(current_push)
                        current_push = None
                    in_chris_block = False
                    continue
                
                # Session matches
                sm = SESSION_MATCH_RE.search(line)
                if sm:
                    entry = {'col': sm.group(1), 'row': int(sm.group(2)), 'val': sm.group(3).strip()}
                    if current_push:
                        current_push['session_matches'].append(entry)
                    all_session_matches.append(entry)
                    total_chris_lines += 1
                    continue
                
                # Matched evals
                me = MATCHED_EVAL_RE.search(line)
                if me:
                    entry = {'idx': int(me.group(1)), 'account': me.group(2), 'phase': me.group(3)}
                    if current_push:
                        current_push['matched_evals'].append(entry)
                    all_matched_evals.append(entry)
                    total_chris_lines += 1
                    continue
                
                # Farming
                fa = FA_RE.search(line)
                if fa:
                    entry = {'account': fa.group(1), 'farming_days': int(fa.group(2))}
                    if current_push:
                        current_push['farming'].append(entry)
                    all_farming.append(entry)
                    total_chris_lines += 1
                    continue
                
                # Final data
                if FINAL_DATA_RE.search(line):
                    if current_push:
                        current_push['final_data'] = True
                    total_chris_lines += 1
                    continue
                
                # Preserved evals
                pm = PRESERVE_RE.search(line)
                if pm:
                    if current_push:
                        current_push['preserve_count'] = int(pm.group(1))
                    total_chris_lines += 1
                    continue
                
                # Data saved
                if SAVE_RE.search(line):
                    if current_push:
                        current_push['data_saved'] = True
                    total_chris_lines += 1
                    continue
                
                # Errors during Chris block
                if ERROR_RE.search(line):
                    ts_m = TS_RE.match(line)
                    ts = ts_m.group(1) if ts_m else ''
                    entry = {'timestamp': ts, 'detail': line.strip()[:200], 'log': lf, 'line': line_num}
                    if current_push:
                        current_push['errors'].append(entry)
                    all_errors.append(entry)
                    total_chris_lines += 1
                    continue
                
                # Count Chris Ream / CHRISREAM lines
                if 'Chris Ream' in line or 'CHRISREAM' in line:
                    total_chris_lines += 1
            
            else:
                # Outside a Chris block - still catch some Chris-specific events
                if 'Chris Ream' in line:
                    total_chris_lines += 1
                    # CSV imports
                    if 'csv' in line.lower() or 'import' in line.lower():
                        ts_m = TS_RE.match(line)
                        ts = ts_m.group(1) if ts_m else ''
                        all_csv_imports.append({'timestamp': ts, 'detail': line.strip()[:200], 'log': lf, 'line': line_num})
                    # Errors outside push blocks
                    if ERROR_RE.search(line):
                        ts_m = TS_RE.match(line)
                        ts = ts_m.group(1) if ts_m else ''
                        all_errors.append({'timestamp': ts, 'detail': line.strip()[:200], 'log': lf, 'line': line_num})
    
    # Close any remaining push
    if current_push:
        pushes.append(current_push)
        current_push = None

print(f'\nTotal lines scanned: {total_lines_scanned:,}')
print(f'Chris Ream related lines: {total_chris_lines:,}')
print(f'Total pushes found: {len(pushes)}')

# ---- REPORT ----

print(f'\n{"="*80}')
print(f'CHRIS REAM COMPREHENSIVE LOG ANALYSIS')
print(f'{"="*80}')

# 1. Push Overview
print(f'\n{"─"*80}')
print(f'1. PUSH OVERVIEW ({len(pushes)} pushes)')
print(f'{"─"*80}')

# Sort pushes by timestamp
pushes.sort(key=lambda p: p['timestamp'])

# Show eval count progression
print(f'\nEval count progression over time:')
prev_evals = 0
jumps = []
for p in pushes:
    change = p['evals'] - prev_evals
    if prev_evals and abs(change) > 10:
        jumps.append((p['timestamp'], prev_evals, p['evals'], change, p['log']))
    prev_evals = p['evals']

if jumps:
    print(f'\n  Significant eval count changes:')
    for ts, old, new, delta, lf in jumps:
        marker = '⚠️' if abs(delta) > 50 else '📊'
        print(f'  {marker} {ts}  {old} -> {new} ({delta:+d})  [{lf}]')

# Eval count milestones
first_ts = pushes[0]['timestamp'] if pushes else 'N/A'
last_ts = pushes[-1]['timestamp'] if pushes else 'N/A'
first_evals = pushes[0]['evals'] if pushes else 0
last_evals = pushes[-1]['evals'] if pushes else 0
print(f'\n  First push: {first_ts} with {first_evals} evals')
print(f'  Last push:  {last_ts} with {last_evals} evals')
print(f'  Eval growth: {first_evals} -> {last_evals}')

# Push frequency
pushes_per_day = Counter()
for p in pushes:
    day = p['timestamp'][:10]
    pushes_per_day[day] += 1

print(f'\n  Pushes per day:')
for day, count in sorted(pushes_per_day.items()):
    bar = '█' * min(count, 50)
    print(f'    {day}: {count:>4} {bar}')

# 2. Session Match Analysis
print(f'\n{"─"*80}')
print(f'2. SESSION MATCH ANALYSIS ({len(all_session_matches)} total matches)')
print(f'{"─"*80}')

field_counts = Counter(sm['col'] for sm in all_session_matches)
row_counts = Counter(sm['row'] for sm in all_session_matches)

print(f'\n  Fields updated:')
for field, count in field_counts.most_common():
    print(f'    {field:<35} {count:>5}x')

print(f'\n  Rows with updates: {len(row_counts)} unique rows')
if row_counts:
    print(f'  Max row index: {max(row_counts.keys())}')
    print(f'\n  Top 15 most-updated rows:')
    for row, count in row_counts.most_common(15):
        print(f'    Row {row:>4}: {count:>4} updates')

# Per-push session match stats
pushes_with_matches = sum(1 for p in pushes if p['session_matches'])
print(f'\n  Pushes with session matches: {pushes_with_matches}/{len(pushes)}')

# 3. Matched Eval Analysis
print(f'\n{"─"*80}')
print(f'3. MATCHED EVAL ANALYSIS ({len(all_matched_evals)} total)')
print(f'{"─"*80}')

unique_accounts = set(me['account'] for me in all_matched_evals)
unique_indices = set(me['idx'] for me in all_matched_evals)
phase_counts = Counter(me['phase'] for me in all_matched_evals)

print(f'  Unique accounts: {len(unique_accounts)}')
print(f'  Unique eval indices: {len(unique_indices)}')
if unique_indices:
    print(f'  Index range: {min(unique_indices)} - {max(unique_indices)}')

print(f'\n  Phase distribution:')
for phase, count in phase_counts.most_common():
    print(f'    {phase:<25} {count:>6}x')

# 4. Farming Analysis
print(f'\n{"─"*80}')
print(f'4. FARMING PRE-COMPUTE ({len(all_farming)} entries)')
print(f'{"─"*80}')

farming_accounts = set(f['account'] for f in all_farming)
farming_days_dist = Counter(f['farming_days'] for f in all_farming)
print(f'  Unique accounts: {len(farming_accounts)}')
print(f'  Farming days distribution:')
for days in sorted(farming_days_dist.keys()):
    count = farming_days_dist[days]
    print(f'    {days:>3} days: {count:>5}x')

# 5. Data Save Status
print(f'\n{"─"*80}')
print(f'5. DATA SAVE STATUS')
print(f'{"─"*80}')

pushes_with_save = sum(1 for p in pushes if p['data_saved'])
pushes_with_final = sum(1 for p in pushes if p['final_data'])
print(f'  Pushes with FINAL DATA: {pushes_with_final}/{len(pushes)}')
print(f'  Pushes with Data Saved: {pushes_with_save}/{len(pushes)}')

# Pushes that had FINAL DATA but NOT saved
failed_saves = [p for p in pushes if p['final_data'] and not p['data_saved']]
if failed_saves:
    print(f'\n  ⚠️ FINAL DATA without Save ({len(failed_saves)}):')
    for p in failed_saves[:10]:
        print(f'    {p["timestamp"]} [{p["log"]}]')

# 6. Errors
print(f'\n{"─"*80}')
print(f'6. ERRORS & EXCEPTIONS ({len(all_errors)})')
print(f'{"─"*80}')

for err in all_errors:
    print(f'  {err["timestamp"]}  {err["detail"][:120]}  [{err["log"]}:{err["line"]}]')

# 7. CSV Imports
print(f'\n{"─"*80}')
print(f'7. CSV IMPORTS ({len(all_csv_imports)})')
print(f'{"─"*80}')

for imp in all_csv_imports:
    print(f'  {imp["timestamp"]}  {imp["detail"][:120]}')

# 8. Data Integrity Checks
print(f'\n{"─"*80}')
print(f'8. DATA INTEGRITY CHECKS')
print(f'{"─"*80}')

# Check for duplicate eval indices being assigned
index_to_accounts = defaultdict(set)
for me in all_matched_evals:
    index_to_accounts[me['idx']].add(me['account'])

multi_account_indices = {idx: accts for idx, accts in index_to_accounts.items() if len(accts) > 1}
if multi_account_indices:
    print(f'\n  ⚠️ Indices mapped to MULTIPLE accounts ({len(multi_account_indices)}):')
    for idx in sorted(multi_account_indices.keys())[:20]:
        accts = multi_account_indices[idx]
        print(f'    idx={idx}: {accts}')
else:
    print(f'\n  ✅ All eval indices map to a single account (no conflicts)')

# Check for account mapped to multiple indices
account_to_indices = defaultdict(set)
for me in all_matched_evals:
    account_to_indices[me['account']].add(me['idx'])

multi_index_accounts = {acct: idxs for acct, idxs in account_to_indices.items() if len(idxs) > 1}
if multi_index_accounts:
    print(f'\n  ⚠️ Accounts mapped to MULTIPLE indices ({len(multi_index_accounts)}):')
    for acct in sorted(multi_index_accounts.keys())[:20]:
        idxs = sorted(multi_index_accounts[acct])
        print(f'    {acct}: indices={idxs}')
else:
    print(f'\n  ✅ All accounts map to a single index')

# Check if session matches target valid row indices
if all_session_matches:
    max_eval = max(p['evals'] for p in pushes)
    out_of_range = [sm for sm in all_session_matches if sm['row'] >= max_eval]
    if out_of_range:
        print(f'\n  ⚠️ Session matches targeting rows >= max evals ({max_eval}): {len(out_of_range)}')
        for sm in out_of_range[:5]:
            print(f'    Row {sm["row"]}: {sm["col"]} = {sm["val"][:50]}')
    else:
        print(f'\n  ✅ All session match rows within valid range (max evals={max_eval})')

# 9. Push Detail Summary
print(f'\n{"─"*80}')
print(f'9. PUSH DETAIL (sampled)')
print(f'{"─"*80}')

# Show stats for pushes with interesting data
interesting = [p for p in pushes if p['session_matches'] or p['errors'] or p['farming']]
print(f'\n  Pushes with interesting activity: {len(interesting)}/{len(pushes)}')

if interesting:
    print(f'\n  Sample pushes with activity:')
    for p in interesting[:10]:
        print(f'    {p["timestamp"]}  evals={p["evals"]} deals={p["deals"]}  '
              f'sessions={len(p["session_matches"])} matched_evals={len(p["matched_evals"])} '
              f'farming={len(p["farming"])} errors={len(p["errors"])} '
              f'final={p["final_data"]} saved={p["data_saved"]}  [{p["log"]}]')

# 10. Overall Health Summary
print(f'\n{"="*80}')
print(f'OVERALL HEALTH SUMMARY')
print(f'{"="*80}')

issues = []
if all_errors:
    issues.append(f'{len(all_errors)} errors/exceptions found')
if multi_account_indices:
    issues.append(f'{len(multi_account_indices)} indices mapped to multiple accounts')
if multi_index_accounts:
    issues.append(f'{len(multi_index_accounts)} accounts mapped to multiple indices')
if failed_saves:
    issues.append(f'{len(failed_saves)} pushes with FINAL DATA but no save confirmation')

if not issues:
    print('  ✅ No major issues detected. Data flow appears healthy.')
else:
    print('  Issues found:')
    for issue in issues:
        print(f'    ⚠️ {issue}')

print(f'\n  Key metrics:')
print(f'    Total pushes: {len(pushes)}')
print(f'    Total session match updates: {len(all_session_matches)}')
print(f'    Total matched evals: {len(all_matched_evals)}')
print(f'    Total farming entries: {len(all_farming)}')
print(f'    Final eval count (last push): {last_evals}')
print(f'    Unique accounts seen: {len(unique_accounts)}')
print(f'    Errors: {len(all_errors)}')
print(f'\n{"="*80}')
print('ANALYSIS COMPLETE')
print(f'{"="*80}')
