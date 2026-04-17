"""Comprehensive line-by-line analysis of ALL Chris Ream log activity.
Categorize every event, check for anomalies, verify data flow."""
import re, os, json
from collections import defaultdict, Counter
from datetime import datetime

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# ---- Pass 1: Extract ALL Chris Ream lines with context ----
# We want lines that mention "Chris Ream" (not "Kelly Ream" or other Reams)
chris_lines = []

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    print(f'Scanning {lf}: {len(lines)} lines...')
    
    for i, line in enumerate(lines):
        # Must contain "Chris Ream" specifically (not just "ream" or "chris")
        if 'Chris Ream' in line:
            chris_lines.append((lf, i, line.rstrip()))
        # Also catch CHRISREAM in account names (dashboard accounts)
        elif 'CHRISREAM' in line:
            chris_lines.append((lf, i, line.rstrip()))

print(f'\nTotal Chris Ream specific lines: {len(chris_lines)}')

# ---- Pass 2: Categorize each line ----
categories = defaultdict(list)  # category -> [(log, line_num, timestamp, detail)]

# Patterns
TIMESTAMP_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
PUSH_RE = re.compile(r'Push for Chris Ream: (\d+) deals, balance=([\d.]+), (\d+) evaluations')
FINAL_DATA_RE = re.compile(r'FINAL DATA TO SAVE for Chris Ream')
CSV_IMPORT_RE = re.compile(r'(?:CSV import|Imported CSV).*Chris')
SESSION_MATCH_RE = re.compile(r'Matched session.*Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)')
DASHBOARD_ACCT_RE = re.compile(r'Dashboard Account:\s*(\S+CHRISREAM\S*)')
PRESERVING_RE = re.compile(r'Preserving (\d+) EXISTING evaluations')
REQUEST_RE = re.compile(r'\[REQUEST\]\s+(POST|GET)\s+(\S+)\s+->\s+(\d+)')
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]')
FA_RE = re.compile(r'\[FA PRE-COMPUTE\]')
AGGREGATED_RE = re.compile(r'Received (\d+) aggregated groups, (\d+) raw deals')
STATS_RE = re.compile(r'Stats calculated')
ERROR_RE = re.compile(r'(?:Error|Exception|Traceback|FAIL|WARNING)', re.IGNORECASE)
SAVE_RE = re.compile(r'save_client_data|Data saved')
HISTORY_RE = re.compile(r'data_history|version.*saved', re.IGNORECASE)

for lf, line_num, line in chris_lines:
    ts_match = TIMESTAMP_RE.match(line)
    ts = ts_match.group(1) if ts_match else ''
    
    if PUSH_RE.search(line):
        m = PUSH_RE.search(line)
        categories['PUSH'].append((lf, line_num, ts, f'{m.group(1)} deals, bal={m.group(2)}, {m.group(3)} evals'))
    elif FINAL_DATA_RE.search(line):
        categories['FINAL_DATA'].append((lf, line_num, ts, 'FINAL DATA TO SAVE'))
    elif CSV_IMPORT_RE.search(line):
        categories['CSV_IMPORT'].append((lf, line_num, ts, line[line.find('CSV'):]))
    elif SESSION_MATCH_RE.search(line):
        m = SESSION_MATCH_RE.search(line)
        categories['SESSION_MATCH'].append((lf, line_num, ts, f'Col=[{m.group(1)}] Row={m.group(2)} Val={m.group(3)[:50]}'))
    elif DASHBOARD_ACCT_RE.search(line):
        m = DASHBOARD_ACCT_RE.search(line)
        categories['DASHBOARD_ACCT'].append((lf, line_num, ts, m.group(1)))
    elif PRESERVING_RE.search(line):
        m = PRESERVING_RE.search(line)
        categories['PRESERVING_EVALS'].append((lf, line_num, ts, f'{m.group(1)} evals'))
    elif REQUEST_RE.search(line):
        m = REQUEST_RE.search(line)
        categories['REQUEST'].append((lf, line_num, ts, f'{m.group(1)} {m.group(2)} -> {m.group(3)}'))
    elif MATCHED_EVAL_RE.search(line):
        categories['MATCHED_EVAL'].append((lf, line_num, ts, line[line.find('[MATCHED'):]))
    elif FA_RE.search(line):
        categories['FARMING'].append((lf, line_num, ts, line[line.find('[FA'):]))
    elif AGGREGATED_RE.search(line):
        m = AGGREGATED_RE.search(line)
        categories['AGGREGATED'].append((lf, line_num, ts, f'{m.group(1)} groups, {m.group(2)} deals'))
    elif STATS_RE.search(line):
        categories['STATS'].append((lf, line_num, ts, 'Stats calculated'))
    elif ERROR_RE.search(line):
        categories['ERROR_WARNING'].append((lf, line_num, ts, line[24:200] if len(line) > 24 else line))
    elif 'balance' in line.lower() or 'deposit' in line.lower() or 'withdrawal' in line.lower():
        categories['FINANCIAL'].append((lf, line_num, ts, line[24:150] if len(line) > 24 else line))
    elif 'hedging' in line.lower() or 'hedge' in line.lower():
        categories['HEDGING'].append((lf, line_num, ts, line[24:150] if len(line) > 24 else line))
    else:
        categories['OTHER'].append((lf, line_num, ts, line[24:150] if len(line) > 24 else line))

# ---- Print category summary ----
print(f'\n{"="*60}')
print(f'CHRIS REAM LOG ANALYSIS - CATEGORY SUMMARY')
print(f'{"="*60}')
total = 0
for cat in sorted(categories.keys(), key=lambda c: -len(categories[c])):
    count = len(categories[cat])
    total += count
    print(f'  {cat:<25} {count:>6}')
print(f'  {"TOTAL":<25} {total:>6}')

# ---- Push Timeline ----
print(f'\n{"="*60}')
print(f'PUSH TIMELINE ({len(categories["PUSH"])} pushes)')
print(f'{"="*60}')

push_evals = []
for lf, ln, ts, detail in categories['PUSH']:
    m = re.search(r'(\d+) evals', detail)
    num_evals = int(m.group(1)) if m else 0
    push_evals.append((ts, num_evals, detail, lf))

# Sort by timestamp
push_evals.sort(key=lambda x: x[0])

# Show eval count progression
prev_evals = 0
anomalies = []
for ts, num_evals, detail, lf in push_evals:
    change = num_evals - prev_evals if prev_evals else 0
    marker = ''
    if prev_evals and abs(change) > 50:
        marker = f' ⚠️ JUMP {change:+d}'
        anomalies.append((ts, f'Eval count jumped from {prev_evals} to {num_evals} ({change:+d})'))
    elif prev_evals and change < 0:
        marker = f' ⬇ DROP {change}'
        anomalies.append((ts, f'Eval count dropped from {prev_evals} to {num_evals} ({change})'))
    
    print(f'  {ts}  {detail:<50} [{lf}]{marker}')
    prev_evals = num_evals

# ---- Preserving Evals timeline (shows server-side eval count) ----
print(f'\n{"="*60}')
print(f'PRESERVING EVALS TIMELINE ({len(categories["PRESERVING_EVALS"])})')
print(f'{"="*60}')

preserve_data = []
for lf, ln, ts, detail in categories['PRESERVING_EVALS']:
    m = re.search(r'(\d+)', detail)
    num = int(m.group(1)) if m else 0
    preserve_data.append((ts, num, lf))

preserve_data.sort(key=lambda x: x[0])
prev = 0
for ts, num, lf in preserve_data:
    change = num - prev if prev else 0
    marker = ''
    if prev and abs(change) > 50:
        marker = f' ⚠️ JUMP {change:+d}'
        anomalies.append((ts, f'Server evals jumped from {prev} to {num} ({change:+d})'))
    elif prev and change < 0:
        marker = f' ⬇ DROP {change}'
    
    print(f'  {ts}  Preserving {num:>5} evals [{lf}]{marker}')
    prev = num

# ---- CSV Imports ----
print(f'\n{"="*60}')
print(f'CSV IMPORTS ({len(categories["CSV_IMPORT"])})')
print(f'{"="*60}')
for lf, ln, ts, detail in sorted(categories['CSV_IMPORT'], key=lambda x: x[2]):
    print(f'  {ts}  {detail[:120]} [{lf}]')

# ---- Errors and Warnings ----
print(f'\n{"="*60}')
print(f'ERRORS & WARNINGS ({len(categories["ERROR_WARNING"])})')
print(f'{"="*60}')
for lf, ln, ts, detail in categories['ERROR_WARNING']:
    print(f'  {ts}  {detail[:120]} [{lf}:{ln}]')

# ---- Dashboard Account Activity ----
print(f'\n{"="*60}')
print(f'DASHBOARD ACCOUNTS SEEN ({len(categories["DASHBOARD_ACCT"])})')
print(f'{"="*60}')
acct_counts = Counter(d for _, _, _, d in categories['DASHBOARD_ACCT'])
for acct, count in acct_counts.most_common(30):
    print(f'  {acct:<40} seen {count:>4}x')

# ---- Session Match Field Distribution ----
print(f'\n{"="*60}')
print(f'SESSION MATCH FIELDS ({len(categories["SESSION_MATCH"])})')
print(f'{"="*60}')
field_counts = Counter()
row_counts = Counter()
for _, _, _, detail in categories['SESSION_MATCH']:
    m = re.match(r'Col=\[([^\]]+)\] Row=(\d+)', detail)
    if m:
        field_counts[m.group(1)] += 1
        row_counts[int(m.group(2))] += 1

print('Fields updated:')
for field, count in field_counts.most_common(20):
    print(f'  {field:<30} {count:>5}x')

print(f'\nRows updated: {len(row_counts)} unique rows')
print(f'Max row index: {max(row_counts.keys()) if row_counts else 0}')
print(f'Most updated rows:')
for row, count in row_counts.most_common(10):
    print(f'  Row {row:>4}: {count:>4} updates')

# ---- Anomalies Summary ----
print(f'\n{"="*60}')
print(f'ANOMALIES DETECTED ({len(anomalies)})')
print(f'{"="*60}')
anomalies.sort()
for ts, desc in anomalies:
    print(f'  {ts}  {desc}')

# ---- Request Patterns ----
print(f'\n{"="*60}')
print(f'REQUEST PATTERNS ({len(categories["REQUEST"])})')
print(f'{"="*60}')
req_types = Counter(d for _, _, _, d in categories['REQUEST'])
for req, count in req_types.most_common(10):
    print(f'  {req:<50} {count:>4}x')

# ---- Financial Data ----
print(f'\n{"="*60}')
print(f'FINANCIAL DATA ({len(categories["FINANCIAL"])})')
print(f'{"="*60}')
for lf, ln, ts, detail in sorted(categories['FINANCIAL'], key=lambda x: x[2])[-20:]:
    print(f'  {ts}  {detail}')

print(f'\n{"="*60}')
print(f'ANALYSIS COMPLETE')
print(f'{"="*60}')
