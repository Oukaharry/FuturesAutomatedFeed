"""Extract FULL eval data from Chris Ream 'FINAL DATA TO SAVE' blocks in logs.
Then do comprehensive field-level audit and fill."""
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

# ---- Extract Chris-specific data from logs ----
log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# We need to capture multi-line blocks after "FINAL DATA TO SAVE for Chris Ream:"
# and also [MATCHED EVAL] lines
MATCHED_EVAL_RE = re.compile(r'\[MATCHED EVAL\]\s+eval_idx=(\d+)\s+account=(\S+)\s+phase=(\w+)')
SESSION_RE = re.compile(r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)')
PUSH_RE = re.compile(r'Push for Chris Ream: (\d+) deals, balance=([\d.]+), (\d+) evaluations')
DASHBOARD_ACCT_RE = re.compile(r'Dashboard Account:\s*(\S+)\s*\((\d+) trades?\)')

# Collect all data
push_events = []  # (log, timestamp, deals, balance, num_evals)  
matched_evals = defaultdict(list)  # eval_idx -> [(account, phase)]
session_accounts = set()
dashboard_accounts = set()
final_data_blocks = []  # (timestamp, raw_text)

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    print(f'  {lf}: {len(lines)} lines')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Only Chris Ream (not Kelly Ream or other Ream)
        if 'Chris Ream' in line:
            # Push event
            m = PUSH_RE.search(line)
            if m:
                ts = line[:23] if len(line) > 23 else ''
                push_events.append((lf, ts, int(m.group(1)), float(m.group(2)), int(m.group(3))))
            
            # FINAL DATA TO SAVE - multi-line JSON block follows
            if 'FINAL DATA TO SAVE for Chris Ream:' in line:
                ts = line[:23] if len(line) > 23 else ''
                # Read subsequent lines that look like data (indented or JSON)
                block_lines = []
                j = i + 1
                while j < len(lines) and j < i + 5000:
                    next_line = lines[j]
                    # Stop at next timestamp line (starts with 20XX-) 
                    if re.match(r'20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', next_line):
                        break
                    block_lines.append(next_line.rstrip())
                    j += 1
                if block_lines:
                    final_data_blocks.append((ts, '\n'.join(block_lines)))
                i = j
                continue
        
        # Also check for CHRISTREAM in dashboard account lines regardless of push owner
        if 'CHRISREAM' in line or 'CHRIS' in line.upper():
            m = DASHBOARD_ACCT_RE.search(line)
            if m:
                dashboard_accounts.add(m.group(1))
        
        # [MATCHED EVAL] lines for Chris's eval indices
        m = MATCHED_EVAL_RE.search(line)
        if m:
            idx = int(m.group(1))
            acct = m.group(2)
            phase = m.group(3)
            matched_evals[idx].append((acct, phase))
        
        m = SESSION_RE.search(line)
        if m:
            session_accounts.add(m.group(1))
        
        i += 1

print(f'\nPush events: {len(push_events)}')
print(f'Final data blocks: {len(final_data_blocks)}')
print(f'Matched eval entries: {sum(len(v) for v in matched_evals.values())} across {len(matched_evals)} indices')
print(f'Dashboard accounts: {len(dashboard_accounts)}')
print(f'Session accounts: {len(session_accounts)}')

# ---- Parse FINAL DATA blocks to extract evaluations ----
log_evals = []  # list of {field: value} dicts from logs
total_parsed = 0

for ts, block in final_data_blocks:
    # The block might be Python repr or JSON
    # Try to find eval-like dicts in the block
    # These are typically in a format like: {'Prop Firm': 'MFF', 'Account #': 'XXX', ...}
    
    # Try parsing as a Python dict
    try:
        # Find all dict-like blocks
        dict_pattern = re.compile(r"\{['\"][^{}]*?['\"]:\s*['\"][^{}]*?['\"](?:,\s*['\"][^{}]*?['\"]:\s*['\"][^{}]*?['\"]\s*)*\}")
        for dm in dict_pattern.finditer(block):
            raw = dm.group()
            try:
                d = eval(raw)  # Python dict syntax
                if isinstance(d, dict) and ('Prop Firm' in d or 'Account #' in d):
                    log_evals.append(d)
                    total_parsed += 1
            except:
                pass
    except:
        pass
    
    # Also try JSON-like parsing
    try:
        # Look for JSON arrays of objects
        arr_pattern = re.compile(r'\[(\s*\{[^[\]]{50,}\}\s*(?:,\s*\{[^[\]]{50,}\}\s*)*)\]', re.DOTALL)
        for am in arr_pattern.finditer(block):
            try:
                cleaned = am.group().replace("'", '"').replace('None', 'null').replace('True','true').replace('False','false')
                arr = json.loads(cleaned)
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict) and ('Prop Firm' in item or 'Account #' in item):
                            log_evals.append(item)
                            total_parsed += 1
            except:
                pass
    except:
        pass

print(f'\nParsed {total_parsed} eval dicts from FINAL DATA blocks')

# If we couldn't parse the blocks, show a sample
if not log_evals and final_data_blocks:
    print(f'\nSample FINAL DATA block ({len(final_data_blocks[0][1])} chars):')
    print(final_data_blocks[0][1][:1000])

# ---- Also extract from _chris_ream_extracted.json if it exists ----
extracted_path = '_chris_ream_extracted.json'
if os.path.exists(extracted_path):
    with open(extracted_path, 'r') as f:
        extracted = json.load(f)
    
    ext_evals = extracted.get('evaluations', [])
    if ext_evals:
        print(f'\nLoaded {len(ext_evals)} evals from {extracted_path}')
        log_evals.extend(ext_evals)
    
    # Also get session accounts
    for sa in extracted.get('session_accounts', []):
        if isinstance(sa, str):
            session_accounts.add(sa)

print(f'\nTotal log eval dicts: {len(log_evals)}')

# ---- Build index of log evals by multiple keys ----
# Key by (firm, date_purchased, account_size) and by Account #
log_by_key = defaultdict(list)
log_by_account = defaultdict(list)

for le in log_evals:
    firm = str(le.get('Prop Firm', '')).strip()
    date = str(le.get('Date Purchased', '')).strip()
    size = str(le.get('Account Size', '')).strip()
    acct = str(le.get('Account #', '')).strip()
    acct1 = str(le.get('Account #.1', '')).strip()
    
    key = (firm, date, size)
    if firm:
        log_by_key[key].append(le)
    if acct:
        log_by_account[acct].append(le)
    if acct1:
        log_by_account[acct1].append(le)

# ---- Comprehensive field audit ----
ALL_FIELDS = set()
for ev in evals:
    ALL_FIELDS.update(ev.keys())

# Key fields that matter most
KEY_FIELDS = [
    'Prop Firm', 'Date Purchased', 'Account Size', 'Account #', 'Account #.1',
    'Date Started', 'Date Ended', 'Status P1', 'Status P2', 'Phase',
    'Best Day', 'Worst Day', 'Profit P1', 'Net P1', 'Profit P2', 'Net P2',
    'Hedge Net', 'Hedge Result 1', 'Payout', 'Payout Date',
    'Farming Profit', 'Total Net Profit', 'Notes',
]

print(f'\n=== FIELD COMPLETENESS (Before Fill) ===')
for f in KEY_FIELDS:
    filled = sum(1 for ev in evals if str(ev.get(f, '') or '').strip())
    pct = filled / len(evals) * 100
    print(f'  {f:<25} {filled:>4}/{len(evals)} ({pct:5.1f}%)')

# ---- Row-by-row fill ----
fills_made = 0
fill_details = []

for i, ev in enumerate(evals):
    firm = str(ev.get('Prop Firm', '') or '').strip()
    date = str(ev.get('Date Purchased', '') or '').strip()
    size = str(ev.get('Account Size', '') or '').strip()
    acct = str(ev.get('Account #', '') or '').strip()
    acct1 = str(ev.get('Account #.1', '') or '').strip()
    
    # Find matching log evals
    matches = []
    
    # By account
    if acct:
        matches.extend(log_by_account.get(acct, []))
    if acct1:
        matches.extend(log_by_account.get(acct1, []))
    
    # By composite key
    key = (firm, date, size)
    if firm:
        matches.extend(log_by_key.get(key, []))
    
    if not matches:
        continue
    
    # For each empty field, try to fill from matches
    for field in ALL_FIELDS:
        if field in ('Row #',):
            continue
        current = str(ev.get(field, '') or '').strip()
        if current:
            continue  # Already has a value
        
        # Find best value from log matches
        for m_ev in matches:
            val = str(m_ev.get(field, '') or '').strip()
            if val:
                ev[field] = val
                fills_made += 1
                if field in KEY_FIELDS:
                    fill_details.append(f'  Row {i}: {field} = {val!r}')
                break

# ---- Also try to fill from matched_evals (account numbers) ----
FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU',
    'Tradeify': 'TDFY',
    'Topstep': 'V2',
    'TradeDay': 'TDF',
    'FundedNext': 'FNFT',
    'Apex Trader Funding': 'APEX',
    'Funding Ticks': 'FTKS',
    'Alpha Futures': 'AFAD',
}
VALID_ACCT = re.compile(r'^[A-Z][A-Z0-9]{1,4}-[A-Z0-9]{3,6}$')

acct_fills = 0
for i, ev in enumerate(evals):
    firm = str(ev.get('Prop Firm', '') or '').strip()
    expected_prefix = FIRM_TO_PREFIX.get(firm, '')
    if not expected_prefix:
        continue
    
    a = str(ev.get('Account #', '') or '').strip()
    a1 = str(ev.get('Account #.1', '') or '').strip()
    
    # Check matched evals for this row index
    candidates = set()
    for acct_raw, phase in matched_evals.get(i, []):
        if VALID_ACCT.match(acct_raw) and acct_raw.startswith(expected_prefix + '-'):
            candidates.add(acct_raw)
    
    if not candidates:
        continue
    
    cands = sorted(candidates)
    if not a or not VALID_ACCT.match(a):
        ev['Account #'] = cands[0]
        acct_fills += 1
        fill_details.append(f'  Row {i}: Account # = {cands[0]!r} (from matched_eval)')
    if (not a1 or not VALID_ACCT.match(a1)) and len(cands) > 1:
        ev['Account #.1'] = cands[1]
        acct_fills += 1
        fill_details.append(f'  Row {i}: Account #.1 = {cands[1]!r} (from matched_eval)')

fills_made += acct_fills

print(f'\n=== FILL RESULTS ===')
print(f'Total fields filled: {fills_made}')
print(f'Account fills from matched_eval: {acct_fills}')
if fill_details:
    for d in fill_details[:50]:
        print(d)
    if len(fill_details) > 50:
        print(f'  ... and {len(fill_details)-50} more')

# ---- Post-fill completeness ----
print(f'\n=== FIELD COMPLETENESS (After Fill) ===')
for f in KEY_FIELDS:
    filled = sum(1 for ev in evals if str(ev.get(f, '') or '').strip())
    pct = filled / len(evals) * 100
    print(f'  {f:<25} {filled:>4}/{len(evals)} ({pct:5.1f}%)')

# ---- Row-by-row empty field count ----
rows_with_empties = []
for i, ev in enumerate(evals):
    empty = [f for f in KEY_FIELDS if not str(ev.get(f, '') or '').strip()]
    if empty:
        rows_with_empties.append((i, ev.get('Prop Firm',''), ev.get('Account #',''), len(empty), empty))

rows_with_empties.sort(key=lambda r: -r[3])
print(f'\n=== ROWS WITH MOST EMPTY KEY FIELDS (top 30) ===')
for row, firm, acct, count, fields in rows_with_empties[:30]:
    print(f'  Row {row:>3}: {str(firm)[:20]:<20} Acct={str(acct)!r:20} Empty={count} [{", ".join(fields[:5])}]')

# ---- Save if fills were made ----
if fills_made > 0:
    # Re-number
    for i, ev in enumerate(evals):
        ev['Row #'] = str(i)
    
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
    db.commit()
    db.close()
    
    # CSV
    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    
    with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in evals:
            row = {fn: ev.get(fn, '') for fn in fieldnames}
            writer.writerow(row)
    
    print(f'\nDB + CSV updated. {fills_made} fills applied.')
else:
    print(f'\nNo fills needed.')

print('\nDone.')
