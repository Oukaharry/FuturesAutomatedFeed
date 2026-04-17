"""Survey all client pushes in logs to understand scope and data availability."""
import re, os
from collections import defaultdict

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Patterns
PUSH_RE = re.compile(r'Push for (.+?):\s*$|Push for (.+?):\s')
SESSION_MATCH_RE = re.compile(
    r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)'
)
SAVE_RE = re.compile(r'FINAL DATA SAVED|Data saved successfully|save_client_data')
PHASE_TAG_RE = re.compile(r'Phase\s+(CH\d|FD\d|FA|DD\d)\s*->\s*\[([^\]]+)\]\s*\(Row\s*#(\d+)\)')
FA_WRITE_RE = re.compile(r'\[FA WRITE\]\s*row=(\d+)\s+account=(\S+).*?Hedge Day\s*(\d+).*?\$?([\d.\-]+)')
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s*eval_idx=(\d+)\s+account=(\S+)\s+phase=(\S+)')

# Count pushes and data per client
client_pushes = defaultdict(int)
client_session_matches = defaultdict(int)
client_phase_tags = defaultdict(int)
client_fa_writes = defaultdict(int)
client_eval_matches = defaultdict(int)
client_dates = defaultdict(set)

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...', flush=True)
    
    current_client = None
    lines_since_push = 0
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            # Detect push start
            m = PUSH_RE.search(line)
            if m:
                name = m.group(1) or m.group(2)
                if name:
                    current_client = name.strip().rstrip(':')
                    client_pushes[current_client] += 1
                    lines_since_push = 0
                    # Extract date
                    ts_m = re.match(r'^(\d{4}-\d{2}-\d{2})', line)
                    if ts_m:
                        client_dates[current_client].add(ts_m.group(1))
                    continue
            
            if current_client:
                lines_since_push += 1
                if lines_since_push > 2000:
                    current_client = None
                    continue
                
                if SESSION_MATCH_RE.search(line):
                    client_session_matches[current_client] += 1
                
                if PHASE_TAG_RE.search(line):
                    client_phase_tags[current_client] += 1
                
                if FA_WRITE_RE.search(line):
                    client_fa_writes[current_client] += 1
                
                if MATCHED_EVAL_RE.search(line):
                    client_eval_matches[current_client] += 1

print(f'\n{"="*100}')
print(f'CLIENT PUSH SUMMARY ({len(client_pushes)} clients)')
print(f'{"="*100}')
print(f'{"Client":<30} {"Pushes":>7} {"Sessions":>9} {"Phases":>7} {"FA":>5} {"Evals":>6} {"Date Range":<25}')
print(f'{"-"*30} {"-"*7} {"-"*9} {"-"*7} {"-"*5} {"-"*6} {"-"*25}')

for client in sorted(client_pushes.keys(), key=lambda c: client_pushes[c], reverse=True):
    dates = sorted(client_dates[client])
    date_range = f'{dates[0]} to {dates[-1]}' if dates else 'N/A'
    print(f'{client:<30} {client_pushes[client]:>7} {client_session_matches[client]:>9} '
          f'{client_phase_tags[client]:>7} {client_fa_writes[client]:>5} '
          f'{client_eval_matches[client]:>6} {date_range}')

# Show last week's activity (since March 29)
print(f'\n{"="*100}')
print(f'CLIENTS WITH ACTIVITY SINCE 2026-03-29 (last week)')
print(f'{"="*100}')
recent_threshold = '2026-03-29'
for client in sorted(client_pushes.keys()):
    recent_dates = [d for d in client_dates[client] if d >= recent_threshold]
    if recent_dates:
        print(f'  {client:<30} {len(recent_dates)} days: {", ".join(sorted(recent_dates))}')
