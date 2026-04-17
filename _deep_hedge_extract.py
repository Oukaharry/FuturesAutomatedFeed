"""Deep extraction of ALL hedge result data from logs for Chris Ream.
Extract from Matched session lines AND any other patterns that contain hedge data."""
import re, os, json, sqlite3
from collections import defaultdict, Counter

LOG_DIR = 'logs'
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# ---- Extract every session match line from Chris push blocks ----
TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
PUSH_START_RE = re.compile(r'Push for Chris Ream: (\d+) deals, balance=([\d.]+), (\d+) evaluations')
PUSH_ANY_RE = re.compile(r'Push for \w')
SESSION_MATCH_RE = re.compile(r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)')

# All hedge-related session matches: (timestamp, col, row, value, log)
hedge_matches = []
all_session_matches = []

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'Scanning {lf}...')
    
    in_chris_block = False
    lines_since_push = 0
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f):
            m = PUSH_START_RE.search(line)
            if m:
                in_chris_block = True
                lines_since_push = 0
                continue
            
            if in_chris_block:
                lines_since_push += 1
                
                if PUSH_ANY_RE.search(line) and 'Chris Ream' not in line:
                    in_chris_block = False
                    continue
                if lines_since_push > 2000:
                    in_chris_block = False
                    continue
                
                sm = SESSION_MATCH_RE.search(line)
                if sm:
                    col = sm.group(1)
                    row = int(sm.group(2))
                    val = sm.group(3).strip()
                    ts_m = TS_RE.match(line)
                    ts = ts_m.group(1) if ts_m else ''
                    
                    all_session_matches.append((ts, col, row, val, lf))
                    
                    if 'hedge' in col.lower() or 'result' in col.lower():
                        hedge_matches.append((ts, col, row, val, lf))

print(f'\nTotal session matches: {len(all_session_matches)}')
print(f'Hedge-related matches: {len(hedge_matches)}')

# ---- Show all unique columns found ----
all_cols = Counter(sm[1] for sm in all_session_matches)
print(f'\nAll columns in session matches:')
for col, count in all_cols.most_common():
    print(f'  {col:<35} {count:>5}x')

# ---- Build row->col->value map (latest value wins) ----
# For hedge results
hedge_data = defaultdict(dict)  # row -> {col: (value, timestamp)}
for ts, col, row, val, lf in all_session_matches:
    if col not in hedge_data[row] or ts > hedge_data[row][col][1]:
        hedge_data[row][col] = (val, ts)

# ---- Load current DB data ----
db = sqlite3.connect('dashboard/dashboard.db')
row_data = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row_data[0]) if row_data else []

print(f'\nCurrent DB evals: {len(evals)}')

hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

# ---- Check what we can fill ----
fills_available = 0
fills_new = 0  # Not already in DB
fills_by_col = Counter()

for row_idx in sorted(hedge_data.keys()):
    if row_idx >= len(evals):
        continue
    for col, (val, ts) in hedge_data[row_idx].items():
        if col in hedge_cols:
            fills_available += 1
            fills_by_col[col] += 1
            
            current = str(evals[row_idx].get(col, '')).strip()
            if not current or current == 'nan':
                fills_new += 1

print(f'\nHedge result values available in logs: {fills_available}')
print(f'Values that would be NEW (currently empty): {fills_new}')
print(f'\nBy column:')
for col in hedge_cols:
    print(f'  {col:<25} {fills_by_col.get(col, 0):>5} available')

# ---- Also check ALL columns for new fills ----
print(f'\n{"="*80}')
print(f'ALL COLUMNS - NEW FILLS AVAILABLE')
print(f'{"="*80}')

all_fills = Counter()
new_fills = Counter()
for row_idx in sorted(hedge_data.keys()):
    if row_idx >= len(evals):
        continue
    for col, (val, ts) in hedge_data[row_idx].items():
        all_fills[col] += 1
        current = str(evals[row_idx].get(col, '')).strip()
        if not current or current == 'nan':
            new_fills[col] += 1

print(f'\nColumn fill availability:')
for col in sorted(all_fills.keys()):
    print(f'  {col:<35} Total: {all_fills[col]:>5}  New: {new_fills[col]:>5}')

# ---- Apply fills ----
applied = 0
applied_by_col = Counter()
for row_idx in sorted(hedge_data.keys()):
    if row_idx >= len(evals):
        continue
    for col, (val, ts) in hedge_data[row_idx].items():
        current = str(evals[row_idx].get(col, '')).strip()
        if not current or current == 'nan':
            evals[row_idx][col] = val
            applied += 1
            applied_by_col[col] += 1

print(f'\n{"="*80}')
print(f'APPLIED {applied} NEW FILLS')
print(f'{"="*80}')
for col in sorted(applied_by_col.keys()):
    print(f'  {col:<35} {applied_by_col[col]:>5} fills')

# ---- Save back to DB ----
if applied > 0:
    db.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
               (json.dumps(evals),))
    db.commit()
    print(f'\n✅ Saved {applied} fills to DB')

# ---- Re-check coverage ----
print(f'\n{"="*80}')
print(f'UPDATED HEDGE RESULT COVERAGE')
print(f'{"="*80}')

for col in hedge_cols:
    filled = sum(1 for ev in evals 
                 if str(ev.get(col, '')).strip() and str(ev.get(col, '')).strip() != 'nan')
    print(f'  {col:<25} {filled:>4}/{len(evals)} ({100*filled/len(evals):.1f}%)')

total_missing = 0
for ev in evals:
    for col in hedge_cols:
        v = str(ev.get(col, '')).strip()
        if not v or v == 'nan':
            total_missing += 1

print(f'\n  Total missing hedge cells: {total_missing} (of {len(evals)*6} = {6*len(evals)})')

# ---- Export updated CSV ----
import csv
all_keys = []
seen = set()
for ev in evals:
    for k in ev.keys():
        if k not in seen:
            all_keys.append(k)
            seen.add(k)

csv_path = r'C:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=all_keys)
    writer.writeheader()
    writer.writerows(evals)

print(f'\n✅ CSV exported to {csv_path} ({len(evals)} rows)')

db.close()
