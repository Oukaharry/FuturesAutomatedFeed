"""Check what columns Chris actually has data in, and sample the FINAL DATA format from logs."""
import json, sqlite3, re, os
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'
LOG_DIR = 'logs'

# ---- What columns are actually populated? ----
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'=== ALL FIELDS AND FILL RATES ===')
all_fields = set()
for ev in evals:
    all_fields.update(ev.keys())

field_counts = {}
for f in sorted(all_fields):
    count = sum(1 for ev in evals if str(ev.get(f, '') or '').strip())
    field_counts[f] = count

# Sort by fill count descending
for f, c in sorted(field_counts.items(), key=lambda x: -x[1]):
    pct = c / len(evals) * 100
    indicator = '✓' if pct > 50 else '○' if pct > 0 else '✗'
    print(f'  {indicator} {f:<35} {c:>4}/{len(evals)} ({pct:5.1f}%)')

# ---- Sample what rows 600+ look like (the sparse ones) ----
print(f'\n=== SAMPLE SPARSE ROWS (600-610) ===')
for i in range(600, min(611, len(evals))):
    ev = evals[i]
    non_empty = {k: v for k, v in ev.items() if str(v or '').strip()}
    print(f'\nRow {i}: {len(non_empty)} fields populated')
    for k, v in sorted(non_empty.items()):
        print(f'  {k}: {v!r}')

# ---- Sample a well-populated row ----
print(f'\n=== SAMPLE WELL-POPULATED ROW (row 0) ===')
ev0 = evals[0]
non_empty = {k: v for k, v in ev0.items() if str(v or '').strip()}
print(f'Row 0: {len(non_empty)} fields populated')
for k, v in sorted(non_empty.items()):
    print(f'  {k}: {v!r}')

# ---- Look at how FINAL DATA appears in logs ----
print(f'\n=== SEARCHING FOR FINAL DATA LOG FORMAT ===')
# Read log.1 (smallest) and find "Chris Ream" pushes
with open(os.path.join(LOG_DIR, 'www.tradeopss.com.error.log.1'), 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'FINAL DATA TO SAVE for Chris' in line:
        print(f'\nLine {i}: {line.rstrip()[:200]}')
        # Show the next 10 lines
        for j in range(1, 15):
            if i + j < len(lines):
                nextline = lines[i+j].rstrip()
                print(f'  +{j}: {nextline[:200]}')
        break

# Also check for push data with eval content
print(f'\n=== SEARCHING FOR PUSH DATA STRUCTURE ===')
for i, line in enumerate(lines):
    if 'Push for Chris Ream' in line:
        # Show context around it
        start = max(0, i-2)
        end = min(len(lines), i+20)
        print(f'\nPush event around line {i}:')
        for j in range(start, end):
            print(f'  [{j}]: {lines[j].rstrip()[:200]}')
        break
