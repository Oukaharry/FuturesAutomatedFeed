"""Search logs for CH2 hedge sessions targeting these specific accounts."""
import re, os

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Short account numbers from the missing accounts
targets = {'5509', '5151', '2421', '93002', '37253'}
# Also full account numbers
full_targets = {
    '50KTC-V2-432909-10905509', '50KTC-V2-432909-51535151', 
    '50KTC-V2-432909-92712421', 'FNFTCHCHRISREAM93002', 'FNFTCHCHRISREAM37253'
}

# Patterns
SESSION_RE = re.compile(r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)')
PHASE_RE = re.compile(r'Phase\s+(CH2|FD2)\s*->\s*\[([^\]]+)\]\s*\(Row\s*#(\d+)\)')
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s*eval_idx=(\d+)\s+account=(\S+)\s+phase=(\S+)')
SESSION_ACCT_RE = re.compile(r'\[SESSION\]\s*account_guess=(\S+).*?best_phase=(\S+).*?profit=([\d.\-]+)')

PUSH_START_RE = re.compile(r'Push for Chris Ream:')
PUSH_ANY_RE = re.compile(r'Push for \w')

# Search for any mention of these accounts in Chris blocks
found_lines = []

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...')
    
    in_chris = False
    lines_since = 0
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            if PUSH_START_RE.search(line):
                in_chris = True
                lines_since = 0
                continue
            
            if in_chris:
                lines_since += 1
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    in_chris = False
                    continue
                if lines_since > 2000:
                    in_chris = False
                    continue
                
                # Check if this line mentions any target account
                for t in targets:
                    if t in line:
                        found_lines.append((lf, line_num, line.rstrip()[:250]))
                        break

print(f'\nFound {len(found_lines)} lines mentioning target accounts')

# Categorize
for lf, ln, line in found_lines:
    # Check what type of line
    if 'Matched session' in line and 'Hedge Result 2' in line:
        print(f'\n  ✅ HR2 SESSION MATCH: [{lf}:{ln}]')
        print(f'     {line}')
    elif 'CH2' in line:
        print(f'\n  🏷️  CH2 PHASE: [{lf}:{ln}]')
        print(f'     {line}')
    elif 'MATCHED EVAL' in line:
        m = MATCHED_EVAL_RE.search(line)
        if m:
            print(f'\n  📌 EVAL MATCH: idx={m.group(1)} acct={m.group(2)} phase={m.group(3)} [{lf}:{ln}]')
    elif '[SESSION]' in line:
        print(f'\n  🔄 SESSION: [{lf}:{ln}]')
        print(f'     {line}')

# Also show what rows 587-591 get in session matches (check all session matches for those row indices)
print(f'\n{"="*80}')
print(f'ALL SESSION MATCHES FOR ROWS 587-591')
print(f'{"="*80}')

target_rows = {587, 588, 589, 590, 591}
for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    in_chris = False
    lines_since = 0
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            if PUSH_START_RE.search(line):
                in_chris = True
                lines_since = 0
                continue
            
            if in_chris:
                lines_since += 1
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    in_chris = False
                    continue
                if lines_since > 2000:
                    in_chris = False
                    continue
                
                sm = SESSION_RE.search(line)
                if sm:
                    row = int(sm.group(2))
                    if row in target_rows:
                        print(f'  Row {row}: Col=[{sm.group(1)}] Val={sm.group(3).strip()[:60]} [{lf}:{line_num}]')
                
                # Also check phase lines for these rows
                pm = PHASE_RE.search(line)
                if pm:
                    row = int(pm.group(3))
                    if row in target_rows:
                        print(f'  🏷️ Row {row}: Phase {pm.group(1)} -> [{pm.group(2)}] [{lf}:{line_num}]')

# Also look at what rows these accounts are matched to over time
print(f'\n{"="*80}')
print(f'EVAL INDEX MAPPING FOR TARGET ACCOUNTS OVER TIME')
print(f'{"="*80}')

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    in_chris = False
    lines_since = 0
    push_ts = ''
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            if PUSH_START_RE.search(line):
                in_chris = True
                lines_since = 0
                ts_m = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                push_ts = ts_m.group(1) if ts_m else ''
                continue
            
            if in_chris:
                lines_since += 1
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    in_chris = False
                    continue
                if lines_since > 2000:
                    in_chris = False
                    continue
                
                m = MATCHED_EVAL_RE.search(line)
                if m:
                    acct = m.group(2)
                    if acct in targets:
                        idx = m.group(1)
                        phase = m.group(3)
                        print(f'  {push_ts} | acct={acct:>6} -> idx={idx:>3} phase={phase} [{lf}]')
