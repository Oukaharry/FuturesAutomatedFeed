"""Peek at actual Chris log lines to understand the format."""
import os, glob

LOG_DIR = 'logs'
log_files = sorted(glob.glob(os.path.join(LOG_DIR, '*.log.*')))

chris_lines = []
for log_file in log_files:
    fname = os.path.basename(log_file)
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f):
            if 'chris' in line.lower() or 'Chris' in line:
                chris_lines.append((fname, i, line.rstrip()))

print(f'Total Chris lines: {len(chris_lines)}')

# Write to file for inspection
with open('_chris_log_samples.txt', 'w', encoding='utf-8') as out:
    out.write(f'Total: {len(chris_lines)}\n\n')
    out.write('=== First 15 ===\n')
    for fname, i, line in chris_lines[:15]:
        out.write(f'[{fname}:{i}] {line[:300]}\n')
    
    acct_lines = [(f, i, l) for f, i, l in chris_lines if 'account' in l.lower()]
    out.write(f'\n=== With "account" ({len(acct_lines)}) ===\n')
    for fname, i, line in acct_lines[:15]:
        out.write(f'[{fname}:{i}] {line[:300]}\n')
    
    row_lines = [(f, i, l) for f, i, l in chris_lines if 'row' in l.lower()]
    out.write(f'\n=== With "row" ({len(row_lines)}) ===\n')
    for fname, i, line in row_lines[:15]:
        out.write(f'[{fname}:{i}] {line[:300]}\n')
    
    push_lines = [(f, i, l) for f, i, l in chris_lines if 'push' in l.lower()]
    out.write(f'\n=== With "push" ({len(push_lines)}) ===\n')
    for fname, i, line in push_lines[:15]:
        out.write(f'[{fname}:{i}] {line[:300]}\n')
    
    sess_lines = [(f, i, l) for f, i, l in chris_lines if 'session' in l.lower()]
    out.write(f'\n=== With "session" ({len(sess_lines)}) ===\n')
    for fname, i, line in sess_lines[:15]:
        out.write(f'[{fname}:{i}] {line[:300]}\n')

    # Also get unique line "types" - first 50 chars of each unique pattern
    patterns = set()
    for _, _, line in chris_lines:
        # Strip timestamp if present
        stripped = line.strip()
        if stripped[:4].isdigit() and '-' in stripped[:10]:
            stripped = stripped[stripped.find(']')+1:].strip() if ']' in stripped[:30] else stripped[20:].strip()
        prefix = stripped[:60]
        patterns.add(prefix)
    
    out.write(f'\n=== Unique line prefixes ({len(patterns)}) ===\n')
    for p in sorted(patterns)[:50]:
        out.write(f'  {p}\n')

print(f'Written to _chris_log_samples.txt')
