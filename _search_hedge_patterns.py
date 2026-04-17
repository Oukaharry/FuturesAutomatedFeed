"""Search for ALL possible hedge result data patterns in logs beyond session matches.
Look for hedge computation results, hedging engine output, etc."""
import re, os
from collections import Counter

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Patterns to search for
patterns = {
    'hedge_result': re.compile(r'[Hh]edge\s*[Rr]esult', re.IGNORECASE),
    'hedge_calc': re.compile(r'hedge.*calc|calc.*hedge', re.IGNORECASE),
    'hedge_value': re.compile(r'hedge.*\$[\d,.]+', re.IGNORECASE),
    'p2_hedge': re.compile(r'[Pp]hase\s*2.*hedge|funded.*hedge|hedge.*funded|hedge.*[Pp]2', re.IGNORECASE),
    'hedging_engine': re.compile(r'hedging.engine|hedge.engine', re.IGNORECASE),
    'hr_dollar': re.compile(r'HR\d.*\$|Hedge Result \d.*\$', re.IGNORECASE),
}

# First, find context around hedge results in Chris blocks
PUSH_START_RE = re.compile(r'Push for Chris Ream:')
PUSH_ANY_RE = re.compile(r'Push for \w')

# Sample some Chris blocks to see what patterns exist  
sample_blocks = []
current_block = []
in_chris = False
sampled = 0

for lf in log_files:
    if sampled >= 5:
        break
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...')
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if PUSH_START_RE.search(line):
                if current_block and in_chris:
                    sample_blocks.append(current_block)
                    sampled += 1
                current_block = [line.rstrip()]
                in_chris = True
                continue
            
            if in_chris:
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    if current_block:
                        sample_blocks.append(current_block)
                        sampled += 1
                    in_chris = False
                    current_block = []
                    continue
                
                current_block.append(line.rstrip())
                if len(current_block) > 3000:
                    sample_blocks.append(current_block)
                    sampled += 1
                    in_chris = False
                    current_block = []

print(f'\nSampled {len(sample_blocks)} push blocks')

# Show structure of first full block
if sample_blocks:
    print(f'\n{"="*80}')
    print(f'SAMPLE PUSH BLOCK STRUCTURE (block 1, {len(sample_blocks[0])} lines)')
    print(f'{"="*80}')
    
    # Classify each line type
    line_types = Counter()
    for line in sample_blocks[0]:
        if 'Matched session' in line:
            line_types['Matched session'] += 1
        elif '[MATCHED EVAL]' in line:
            line_types['MATCHED EVAL'] += 1
        elif '[FA PRE-COMPUTE]' in line:
            line_types['FA PRE-COMPUTE'] += 1
        elif 'FINAL DATA TO SAVE' in line:
            line_types['FINAL DATA TO SAVE'] += 1
        elif 'Push for' in line:
            line_types['Push header'] += 1
        elif 'Dashboard Account' in line:
            line_types['Dashboard Account'] += 1
        elif 'hedge' in line.lower() or 'result' in line.lower():
            line_types['Other hedge/result'] += 1
        elif line.strip():
            line_types['Other'] += 1
    
    print(f'\nLine type distribution:')
    for lt, count in line_types.most_common():
        print(f'  {lt:<30} {count:>5}')
    
    # Show the first 50 lines to see structure
    print(f'\nFirst 80 lines of block:')
    for line in sample_blocks[0][:80]:
        print(f'  {line[:150]}')
    
    # Show any lines with "hedge" that are NOT session matches
    print(f'\n\nNon-session-match hedge lines in this block:')
    for line in sample_blocks[0]:
        if ('hedge' in line.lower() or 'result' in line.lower()) and 'Matched session' not in line:
            print(f'  {line[:200]}')

# Now search broadly for hedge patterns NOT in session matches
print(f'\n{"="*80}')
print(f'BROAD SEARCH: Hedge patterns in Chris blocks (not session matches)')
print(f'{"="*80}')

non_session_hedge = []
in_chris = False
lines_count = 0

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if PUSH_START_RE.search(line):
                in_chris = True
                lines_count = 0
                continue
            
            if in_chris:
                lines_count += 1
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    in_chris = False
                    continue
                if lines_count > 2000:
                    in_chris = False
                    continue
                
                if ('hedge' in line.lower()) and 'Matched session' not in line and 'MATCHED EVAL' not in line:
                    non_session_hedge.append((lf, line.rstrip()[:200]))

print(f'Non-session hedge lines found: {len(non_session_hedge)}')
# Classify them
nsh_types = Counter()
for lf, line in non_session_hedge:
    if 'account' in line.lower() and 'hedge' in line.lower():
        nsh_types['account+hedge'] += 1
    elif '$' in line:
        nsh_types['dollar value'] += 1
    else:
        nsh_types['other'] += 1

for t, c in nsh_types.most_common():
    print(f'  {t}: {c}')

# Show samples
for lf, line in non_session_hedge[:30]:
    print(f'  [{lf}] {line}')
