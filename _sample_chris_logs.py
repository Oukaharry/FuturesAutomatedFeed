"""Sample Chris log lines to understand format, then do comprehensive audit."""
import json, sqlite3, re, os, csv
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
LOG_DIR = 'logs'

# ---- Load current DB state ----
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()
print(f'Current DB: {len(evals)} evals')

# ---- Sample Chris log lines to understand format ----
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

chris_lines = []
chris_re = re.compile(r'chris|ream', re.IGNORECASE)

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if chris_re.search(line):
                chris_lines.append((lf, line.rstrip()))

print(f'Total Chris log lines: {len(chris_lines)}')

# Show diverse samples
print('\n=== SAMPLE LOG LINES (first 20 unique patterns) ===')
seen_patterns = set()
samples = []
for lf, line in chris_lines:
    # Create a "pattern" by replacing specific values
    pattern = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', 'DATETIME', line[:200])
    pattern = re.sub(r'\d{5,}', 'NUM', pattern)
    if pattern not in seen_patterns:
        seen_patterns.add(pattern)
        samples.append((lf, line))
        if len(samples) >= 30:
            break

for lf, line in samples:
    print(f'\n[{lf}] {line[:300]}')
    if len(line) > 300:
        print(f'  ... (total {len(line)} chars)')
