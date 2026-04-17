"""Search for ALL CH2 sessions in logs and check which ones failed to match."""
import re, os

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Full account numbers we care about
full_targets = {
    '50KTC-V2-432909-10905509', '50KTC-V2-432909-51535151', 
    '50KTC-V2-432909-92712421', 'FNFTCHCHRISREAM93002', 'FNFTCHCHRISREAM37253'
}
# Short trailing digits
short_targets = {'5509', '5151', '2421', '93002', '37253',
                 '10905509', '51535151', '92712421'}

# Search for all CH2-related lines in Chris blocks
PUSH_START_RE = re.compile(r'Push for Chris Ream:')
PUSH_ANY_RE = re.compile(r'Push for \w')

ch2_lines = []

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...')
    
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
                
                # Check if line mentions CH2 and any of our targets
                if 'CH2' in line or '_CH2' in line:
                    for t in short_targets:
                        if t in line:
                            ch2_lines.append((lf, line_num, push_ts, line.rstrip()[:300]))
                            break
                
                # Also check "Hedge Result 2" lines for our targets
                if 'Hedge Result 2' in line:
                    for t in short_targets:
                        if t in line:
                            ch2_lines.append((lf, line_num, push_ts, line.rstrip()[:300]))
                            break

                # Check for skip/warning messages about these accounts
                if ('skip' in line.lower() or 'no valid' in line.lower() or 
                    'no match' in line.lower() or '⚠' in line or '⏩' in line):
                    for t in short_targets:
                        if t in line:
                            ch2_lines.append((lf, line_num, push_ts, line.rstrip()[:300]))
                            break

print(f'\nFound {len(ch2_lines)} CH2-related lines for target accounts')
for lf, ln, ts, line in ch2_lines:
    print(f'\n  [{ts}] {lf}:{ln}')
    print(f'  {line}')

# Also: search for ALL CH2 sessions to see total success rate
print(f'\n{"="*80}')
print(f'CH2 SESSION SUCCESS/FAIL STATS')
print(f'{"="*80}')

ch2_matched = 0
ch2_skipped = 0
ch2_phase_tags = 0

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
                
                if 'Matched session' in line and 'Hedge Result 2' in line:
                    ch2_matched += 1
                
                if re.search(r'Phase CH2\s*->', line):
                    ch2_phase_tags += 1
                
                if 'CH2' in line and ('skip' in line.lower() or 'no valid' in line.lower() or 
                    'no match' in line.lower() or '⏩' in line):
                    ch2_skipped += 1

print(f'  CH2 Phase Tags (🏷️): {ch2_phase_tags}')
print(f'  CH2 Session Matches (✅): {ch2_matched}')
print(f'  CH2 Skipped/No match: {ch2_skipped}')

# Now search for ALL "session" blocks that mention these accounts - not just CH2
print(f'\n{"="*80}')
print(f'ALL SESSION BLOCKS MENTIONING TARGET SHORT ACCTS')
print(f'{"="*80}')

SESSION_START_RE = re.compile(r'\[SESSION\].*?account_guess=(\S+)')

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
                
                m = SESSION_START_RE.search(line)
                if m:
                    acct = m.group(1)
                    for t in short_targets:
                        if t in acct or acct in full_targets:
                            print(f'  [{ts}] {lf}:{line_num}: {line.rstrip()[:250]}')
                            break
