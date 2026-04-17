"""Extract eval-level data from 'Matched session' log lines for Chris.
These contain: Column: [X] | Row: Y | New Value: Z"""
import json, sqlite3, re, os, csv
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOG_DIR = 'logs'

# Load current DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()
print(f'Current DB: {len(evals)} evals')

# ---- Extract Matched session lines from ALL logs ----
# Format: ✅ Matched session (Start DATETIME) -> Column: [FIELD] | Row: N | New Value: VALUE
MATCH_RE = re.compile(
    r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+?)$'
)

# Also: [MATCHED EVAL] eval_idx=N account=XXXX phase=PHASE
EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')

# [FA PRE-COMPUTE] account=MFFU-66028 farming_days=6 dates=[...]
FA_RE = re.compile(r'\[FA PRE-COMPUTE\]\s+account=(\S+)\s+farming_days=(\d+)')

# Also look for push context to know which client these belong to
PUSH_RE = re.compile(r'Push for Chris Ream:.*?(\d+) evaluations')

log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Collect per-push data keyed by (log, push_line_num)
# For each push, collect all matched session data that came before it
all_field_updates = defaultdict(dict)  # eval_idx -> {field: value}
all_eval_accounts = defaultdict(set)   # eval_idx -> set of accounts
farming_data = defaultdict(int)        # account -> max farming_days

# We need to read the logs and identify which matched session lines belong to Chris pushes
# Strategy: read log forward, track whether we're in a "Chris Ream" push context
for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    print(f'  {lf}: {len(lines)} lines')
    
    # Find all Chris Ream push locations
    chris_pushes = []
    for i, line in enumerate(lines):
        if PUSH_RE.search(line):
            chris_pushes.append(i)
    
    if not chris_pushes:
        print(f'    No Chris pushes')
        continue
    
    print(f'    {len(chris_pushes)} Chris pushes')
    
    # For each push, look backwards to find the matched session lines
    # that came after the previous push (or start of log)
    for push_idx, push_line in enumerate(chris_pushes):
        # Look backwards and forward from push for matched session lines
        # They appear BEFORE the "📥 Push for Chris Ream" line
        # And also the [MATCHED EVAL] lines appear AFTER
        
        # Look backward up to 2000 lines for matched session lines
        start = max(0, push_line - 2000) if push_idx == 0 else max(chris_pushes[push_idx-1], push_line - 2000)
        
        for i in range(start, push_line):
            line = lines[i]
            m = MATCH_RE.search(line)
            if m:
                field = m.group(1)
                row = int(m.group(2))
                value = m.group(3).strip()
                if value:
                    all_field_updates[row][field] = value
        
        # Look forward for [MATCHED EVAL] and [FA PRE-COMPUTE]
        end = chris_pushes[push_idx + 1] if push_idx + 1 < len(chris_pushes) else min(len(lines), push_line + 5000)
        
        for i in range(push_line, end):
            line = lines[i]
            m = EVAL_RE.search(line)
            if m:
                idx = int(m.group(1))
                acct = m.group(2)
                all_eval_accounts[idx].add(acct)
            
            m = FA_RE.search(line)
            if m:
                acct = m.group(1)
                days = int(m.group(2))
                farming_data[acct] = max(farming_data[acct], days)

print(f'\nField updates: {sum(len(v) for v in all_field_updates.values())} across {len(all_field_updates)} rows')
print(f'Eval accounts: {sum(len(v) for v in all_eval_accounts.values())} across {len(all_eval_accounts)} rows')
print(f'Farming data: {len(farming_data)} accounts')

# ---- Which log row indices map to current eval indices? ----
# The log rows were based on historical eval counts (656, 649, etc.)
# Build a mapping using account numbers as anchors

# Current eval account lookup
current_by_acct = {}
for i, ev in enumerate(evals):
    a = str(ev.get('Account #', '') or '').strip()
    a1 = str(ev.get('Account #.1', '') or '').strip()
    if a:
        current_by_acct[a] = i
    if a1:
        current_by_acct[a1] = i

# Map log row -> current row using account numbers from [MATCHED EVAL]
log_to_current = {}
for log_idx, accounts in all_eval_accounts.items():
    for acct in accounts:
        if acct in current_by_acct:
            log_to_current[log_idx] = current_by_acct[acct]
            break

# Also try direct mapping for rows that haven't shifted
for log_idx in all_field_updates:
    if log_idx not in log_to_current and log_idx < len(evals):
        # Check if the eval at this position seems like a match
        # by comparing Prop Firm
        log_to_current[log_idx] = log_idx  # tentative

print(f'\nLog->Current row mappings: {len(log_to_current)}')
mapped_updates = sum(1 for r in all_field_updates if r in log_to_current)
print(f'Rows with field updates AND mapping: {mapped_updates}')

# ---- Apply field updates ----
fills_made = 0
fill_details = []

SKIP_FIELDS = {'Row #'}

for log_idx, fields in sorted(all_field_updates.items()):
    current_idx = log_to_current.get(log_idx)
    if current_idx is None or current_idx >= len(evals):
        continue
    
    ev = evals[current_idx]
    for field, value in fields.items():
        if field in SKIP_FIELDS:
            continue
        current = str(ev.get(field, '') or '').strip()
        if not current and value:
            ev[field] = value
            fills_made += 1
            fill_details.append(f'  Row {current_idx} (log {log_idx}): {field} = {value!r}')

# ---- Apply farming data ----
farming_fills = 0
for acct, days in farming_data.items():
    if acct in current_by_acct:
        idx = current_by_acct[acct]
        ev = evals[idx]
        current = str(ev.get('Farming Days', '') or '').strip()
        if not current:
            ev['Farming Days'] = str(days)
            farming_fills += 1

fills_made += farming_fills

print(f'\n=== FILL RESULTS ===')
print(f'Total fields filled from matched session lines: {fills_made - farming_fills}')
print(f'Farming days filled: {farming_fills}')
print(f'Total fills: {fills_made}')

if fill_details:
    for d in fill_details[:50]:
        print(d)
    if len(fill_details) > 50:
        print(f'  ... and {len(fill_details)-50} more')

# ---- Show field distribution of updates ----
field_update_counts = Counter()
for fields in all_field_updates.values():
    for f in fields:
        field_update_counts[f] += 1

print(f'\n=== FIELD UPDATE DISTRIBUTION IN LOGS ===')
for f, c in field_update_counts.most_common(30):
    print(f'  {f:<30} {c:>5} updates in logs')

# ---- Post-fill completeness ----
KEY_FIELDS = [
    'Prop Firm', 'Date Purchased', 'Account Size', 'Account #', 'Account #.1',
    'Date Started', 'Date Ended', 'Status P1', 'Status', 'Fee',
    'Hedge Net', 'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 1.1',
    'Hedge Net.1', 'Payout 1', 'Farming Net',
]

print(f'\n=== FIELD COMPLETENESS (After Fill) ===')
for f in KEY_FIELDS:
    filled = sum(1 for ev in evals if str(ev.get(f, '') or '').strip())
    pct = filled / len(evals) * 100
    print(f'  {f:<25} {filled:>4}/{len(evals)} ({pct:5.1f}%)')

# ---- Rows still sparse ----
sparse_rows = []
for i, ev in enumerate(evals):
    non_empty = sum(1 for k, v in ev.items() if str(v or '').strip() and k != 'Row #')
    if non_empty < 8:
        sparse_rows.append((i, non_empty, str(ev.get('Prop Firm','')), str(ev.get('Account #',''))))

print(f'\n=== SPARSE ROWS (<8 fields) ===')
print(f'Count: {len(sparse_rows)}')
for row, cnt, firm, acct in sparse_rows[:20]:
    print(f'  Row {row:>3}: {cnt} fields, {firm}, {acct}')

# ---- Check for duplicate rows that made it through ----
seen_keys = {}
dupes_found = []
for i, ev in enumerate(evals):
    a = str(ev.get('Account #', '') or '').strip()
    a1 = str(ev.get('Account #.1', '') or '').strip()
    firm = str(ev.get('Prop Firm', '') or '').strip()
    key = (firm, a, a1)
    if key in seen_keys and a:
        dupes_found.append((i, seen_keys[key], key))
    else:
        seen_keys[key] = i

if dupes_found:
    print(f'\n=== REMAINING DUPLICATES ===')
    for i, prev, key in dupes_found:
        print(f'  Row {i} = Row {prev}: {key}')
else:
    print(f'\nNo duplicates found.')

# ---- Save ----
if fills_made > 0:
    for i, ev in enumerate(evals):
        ev['Row #'] = str(i)
    
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
    db.commit()
    db.close()
    
    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    
    with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in evals:
            row = {fn: ev.get(fn, '') for fn in fieldnames}
            writer.writerow(row)
    
    print(f'\nDB + CSV updated with {fills_made} fills.')
else:
    print(f'\nNo fills to apply.')

print('\nDone.')
