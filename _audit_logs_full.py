"""Full audit of Chris's 635 evals against ALL log data.
Extract every piece of data from logs for Chris, then fill in empty fields."""
import json, sqlite3, re, os, csv
from collections import defaultdict

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

# ---- Comprehensive log parsing ----
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])
print(f'Log files: {log_files}')

# Extract ALL Chris-related log entries
chris_entries = []
chris_patterns = re.compile(r'chris|ream', re.IGNORECASE)

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        if chris_patterns.search(line):
            chris_entries.append((lf, i, line.strip()))

print(f'\nTotal Chris-related log lines: {len(chris_entries)}')

# ---- Parse structured data from logs ----
# Patterns we've seen in logs:
# 1. MATCHED EVAL: session_account=XXXXX -> eval row with fields
# 2. SESSION events with account data
# 3. Push data with eval field values

# Pattern for eval field data in log lines
eval_data_pattern = re.compile(
    r"'session_account':\s*'([^']*)'.*?'eval_data':\s*({[^}]+})",
    re.DOTALL
)

# Pattern for MATCHED EVAL lines
matched_eval_pattern = re.compile(
    r'MATCHED EVAL.*?session_account=(\S+).*?eval_index=(\d+)',
    re.IGNORECASE
)

# More general data extraction patterns  
account_in_log = re.compile(r"(?:account|session_account|acct)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]{5,})")
push_data_pattern = re.compile(r"push.*?data.*?({.*})", re.IGNORECASE | re.DOTALL)

# Extract structured entries
structured_data = []
session_accounts = defaultdict(set)  # account -> set of (field, value) pairs

for lf, line_num, line in chris_entries:
    # Try MATCHED EVAL pattern
    m = matched_eval_pattern.search(line)
    if m:
        acct = m.group(1)
        idx = int(m.group(2))
        
        # Extract any field:value pairs from the line
        fields = {}
        # Look for common patterns like field=value or 'field': 'value'
        kv_pattern = re.compile(r"'(\w[\w\s#.]+?)'\s*:\s*'([^']*)'")
        for km in kv_pattern.finditer(line):
            fields[km.group(1)] = km.group(2)
        
        structured_data.append({
            'type': 'MATCHED_EVAL',
            'account': acct,
            'eval_index': idx,
            'fields': fields,
            'source': f'{lf}:{line_num}'
        })
        session_accounts[acct].update(fields.items())
    
    # Try to find JSON-like data blocks
    json_blocks = re.findall(r'\{[^{}]{20,}\}', line)
    for block in json_blocks:
        try:
            # Clean up Python dict syntax to JSON
            cleaned = block.replace("'", '"').replace('None', 'null').replace('True', 'true').replace('False', 'false')
            data = json.loads(cleaned)
            if isinstance(data, dict):
                acct = data.get('session_account', data.get('Account #', data.get('account', '')))
                if acct:
                    structured_data.append({
                        'type': 'JSON_BLOCK',
                        'account': str(acct),
                        'fields': {str(k): str(v) for k, v in data.items() if v},
                        'source': f'{lf}:{line_num}'
                    })
                    session_accounts[str(acct)].update(
                        (str(k), str(v)) for k, v in data.items() if v
                    )
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Extract account numbers from the line
    for am in account_in_log.finditer(line):
        acct = am.group(1)
        if acct not in session_accounts:
            session_accounts[acct] = set()

print(f'\nStructured data entries: {len(structured_data)}')
print(f'Unique session accounts found: {len(session_accounts)}')

# ---- Map session_accounts to eval rows ----
# Build lookup from Account # and Account #.1 to eval index
acct_to_eval = {}
for i, ev in enumerate(evals):
    a1 = (ev.get('Account #') or '').strip()
    a2 = (ev.get('Account #.1') or '').strip()
    if a1:
        acct_to_eval[a1] = i
        # Also try to extract the numeric suffix for matching partial accounts
        nums = re.findall(r'\d{4,}', a1)
        for n in nums:
            acct_to_eval[f'partial_{n}'] = i
    if a2:
        acct_to_eval[a2] = i
        nums = re.findall(r'\d{4,}', a2)
        for n in nums:
            if f'partial_{n}' not in acct_to_eval:
                acct_to_eval[f'partial_{n}'] = i

# ---- Audit: Check each eval row for empty fields ----
# Key fields that should be populated
KEY_FIELDS = [
    'Prop Firm', 'Date Purchased', 'Account Size', 'Account #', 'Account #.1',
    'Date Started', 'Date Ended', 'Status P1', 'Status P2', 'Phase',
    'Best Day', 'Worst Day', 'Profit P1', 'Net P1', 'Profit P2', 'Net P2',
    'Hedge Net', 'Hedge Result 1', 'Payout', 'Payout Date',
    'Farming Profit', 'Total Net Profit',
]

# Count empty fields per row
empty_field_counts = []
rows_needing_attention = []

for i, ev in enumerate(evals):
    empty_fields = []
    for f in KEY_FIELDS:
        val = (ev.get(f) or '').strip()
        if not val:
            empty_fields.append(f)
    
    empty_field_counts.append(len(empty_fields))
    
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    acct = (ev.get('Account #') or '').strip()
    date = (ev.get('Date Purchased') or '').strip()
    
    if len(empty_fields) > 0:
        rows_needing_attention.append({
            'row': i,
            'firm': firm,
            'date': date,
            'status': status,
            'account': acct,
            'empty_count': len(empty_fields),
            'empty_fields': empty_fields
        })

# ---- Summary stats ----
print(f'\n=== AUDIT SUMMARY ===')
print(f'Total evals: {len(evals)}')
print(f'Rows with at least 1 empty key field: {len(rows_needing_attention)}')

# Group by number of empty fields
from collections import Counter
empty_dist = Counter(empty_field_counts)
print(f'\nEmpty field distribution:')
for n in sorted(empty_dist.keys()):
    print(f'  {n} empty fields: {empty_dist[n]} rows')

# ---- Check completely empty critical fields ----
print(f'\n=== FIELD COMPLETENESS ===')
for f in KEY_FIELDS:
    filled = sum(1 for ev in evals if (ev.get(f) or '').strip())
    pct = filled / len(evals) * 100
    print(f'  {f:<25} {filled:>4}/{len(evals)} ({pct:5.1f}%)')

# ---- Identify worst rows (most empty key fields) ----
rows_needing_attention.sort(key=lambda r: -r['empty_count'])
print(f'\n=== TOP 20 ROWS NEEDING ATTENTION ===')
for r in rows_needing_attention[:20]:
    print(f'  Row {r["row"]:>3}: {r["firm"]:<22} {r["date"]:>12} Status={r["status"]:<15} '
          f'Acct={r["account"]!r} Empty={r["empty_count"]} [{", ".join(r["empty_fields"][:5])}...]')

# ---- Try to fill from logs ----
fills_made = 0
fill_details = []

# Map log session_account numbers to existing eval accounts
# Common prefix patterns: MFFU-XXXXX -> MFFUEVSTP372280XXXXX etc.
PREFIX_MAP = {
    'MFFU': 'My Funded Futures',
    'TDFY': 'Tradeify', 
    'V2': 'Topstep',
    'TDF': 'TradeDay',
    'FNFT': 'FundedNext',
    'APEX': 'Apex Trader Funding',
    'FTKS': 'Funding Ticks',
    'AFAD': 'Alpha Futures',
}

for acct, field_values in session_accounts.items():
    if not field_values:
        continue
    
    # Try direct match
    eval_idx = acct_to_eval.get(acct)
    
    # Try partial match by numeric suffix
    if eval_idx is None:
        nums = re.findall(r'\d{4,}', acct)
        for n in nums:
            eval_idx = acct_to_eval.get(f'partial_{n}')
            if eval_idx is not None:
                break
    
    if eval_idx is not None:
        ev = evals[eval_idx]
        for field, value in field_values:
            if field in ('session_account', 'eval_index', 'row_index'):
                continue
            current = (ev.get(field) or '').strip()
            if not current and value.strip():
                ev[field] = value
                fills_made += 1
                fill_details.append(f'  Row {eval_idx}: {field} = {value!r} (from account {acct})')

print(f'\n=== LOG FILL RESULTS ===')
print(f'Fields filled from logs: {fills_made}')
if fill_details:
    for d in fill_details[:30]:
        print(d)
    if len(fill_details) > 30:
        print(f'  ... and {len(fill_details)-30} more')

# ---- Re-check after fills ----
if fills_made > 0:
    print(f'\n=== AFTER FILL COMPLETENESS ===')
    for f in KEY_FIELDS:
        filled = sum(1 for ev in evals if (ev.get(f) or '').strip())
        pct = filled / len(evals) * 100
        print(f'  {f:<25} {filled:>4}/{len(evals)} ({pct:5.1f}%)')

# Save if we made fills
if fills_made > 0:
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
    db.commit()
    db.close()
    
    # Update CSV
    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    
    with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in evals:
            row = {fn: ev.get(fn, '') for fn in fieldnames}
            writer.writerow(row)
    
    print(f'\nDB and CSV updated with {fills_made} fills.')
else:
    print('\nNo fills needed from logs.')

print('\nDone.')
