"""
Reconstruct client hedge data from server logs.
For each client:
  1. Parse all session match lines from logs (the LAST value wins per cell)
  2. Compare with current DB state
  3. Fill only empty DB cells where logs have data
  4. Export a CSV per client showing what was recovered 
  5. Optionally apply to DB

Designed to run on the server (PythonAnywhere) with logs in the same directory.
"""
import re, os, sys, json, csv, sqlite3
from collections import defaultdict
from datetime import datetime

# Fix Windows terminal encoding for emoji
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================================
# CONFIG - adjust paths for server vs local
# ============================================================
# Local paths (for testing)
LOG_DIR = 'logs'
DB_PATH = 'dashboard/dashboard.db'
OUTPUT_DIR = 'recovery_output'

# Server paths (uncomment when running on PythonAnywhere)
# LOG_DIR = '/var/log'  
# DB_PATH = '/home/Oukaharry/MT5Dashboard/dashboard/dashboard.db'
# OUTPUT_DIR = '/home/Oukaharry/MT5Dashboard/recovery_output'

DRY_RUN = '--apply' not in sys.argv  # Default: dry run. Pass --apply to write DB.
SINGLE_CLIENT = None  # Set to a client name to test one client only
if '--client' in sys.argv:
    idx = sys.argv.index('--client')
    if idx + 1 < len(sys.argv):
        SINGLE_CLIENT = sys.argv[idx + 1]

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# STEP 1: Parse all logs, extract session matches per client
# ============================================================
# The log pattern we're looking for:
#   Push for {client_name}: ...
#   ... (within 2000 lines of the push) ...
#   ✅ Matched session ... -> Column: [{col_name}] | Row: {row} | New Value: ${value}
#
# Row in logs = Excel row (eval_index + 2), so eval_index = row - 2
# The LAST session match per (client, eval_index, column) wins (most recent push)

PUSH_RE = re.compile(r'Push for (.+?):\s')
SESSION_MATCH_RE = re.compile(
    r'Matched session.*?Column:\s*\[([^\]]+)\]\s*\|\s*Row:\s*(\d+)\s*\|\s*New Value:\s*(.+)'
)
# Also capture phase tag lines for context
PHASE_TAG_RE = re.compile(r'Phase\s+(CH\d|FD\d|FA|DD\d)\s*->\s*\[([^\]]+)\]\s*\(Row\s*#(\d+)\)')
# FA WRITE lines
FA_WRITE_RE = re.compile(r'\[FA WRITE\]\s*row=(\d+).*?(?:Hedge Day\s*(\d+)).*?\$?([\d.\-]+)')
# Error lines
ERROR_RE = re.compile(r'(?:Error|Traceback|Exception|database disk image)', re.IGNORECASE)
# Save confirmation
SAVE_RE = re.compile(r'FINAL DATA TO SAVE for (.+?):|Data pushed for (.+?)\s')

log_files = sorted([f for f in os.listdir(LOG_DIR) if 'error.log' in f])

# Structure: client_name -> { (eval_index, column_name) -> (value, timestamp, log_file) }
# We keep the LAST value per cell (latest push)
client_cells = defaultdict(dict)
# Also track push metadata
client_push_count = defaultdict(int)
client_push_dates = defaultdict(set)
client_errors = defaultdict(int)
# Track push timestamps so we know ordering
push_order = 0

# Hedge result columns we care about
HEDGE_COLS = {
    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
    'Hedge Result 4', 'Hedge Result 5',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
    'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6.1', 'Hedge Result 7.1',
}
# Farming columns
FARMING_COLS = set(f'Hedge Day {i}' for i in range(1, 51))
ALL_TRACKED_COLS = HEDGE_COLS | FARMING_COLS

print(f"{'='*80}")
print(f"LOG RECOVERY TOOL")
print(f"{'='*80}")
print(f"Mode: {'DRY RUN (preview only)' if DRY_RUN else '⚠️  APPLYING TO DATABASE'}")
if SINGLE_CLIENT:
    print(f"Client filter: {SINGLE_CLIENT}")
print(f"Log directory: {LOG_DIR}")
print(f"Database: {DB_PATH}")
print(f"Output: {OUTPUT_DIR}/")
print()

for lf in log_files:
    path = os.path.join(LOG_DIR, lf)
    print(f'  Scanning {lf}...', flush=True)
    
    current_client = None
    lines_since_push = 0
    push_ts = ''
    push_had_save = False
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            # Detect push start
            m = PUSH_RE.search(line)
            if m:
                name = m.group(1).strip().rstrip(':')
                
                # If filtering to single client, skip others
                if SINGLE_CLIENT and name != SINGLE_CLIENT:
                    current_client = None
                    continue
                
                current_client = name
                client_push_count[current_client] += 1
                lines_since_push = 0
                push_order += 1
                
                # Extract timestamp
                ts_m = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                push_ts = ts_m.group(1) if ts_m else ''
                if push_ts:
                    client_push_dates[current_client].add(push_ts[:10])
                continue
            
            if current_client is None:
                continue
                
            lines_since_push += 1
            if lines_since_push > 2000:
                current_client = None
                continue
            
            # Check for errors in this push
            if ERROR_RE.search(line):
                client_errors[current_client] += 1
            
            # Session match line — THE GOLD
            sm = SESSION_MATCH_RE.search(line)
            if sm:
                col_name = sm.group(1).strip()
                row_num = int(sm.group(2))
                raw_value = sm.group(3).strip()
                
                # Row in logs = Excel row. eval_index = row - 2
                eval_idx = row_num - 2
                
                if eval_idx < 0:
                    continue  # Invalid row
                
                # Only track hedge/farming columns
                if col_name in ALL_TRACKED_COLS:
                    # Store with push_order so last push wins
                    key = (eval_idx, col_name)
                    client_cells[current_client][key] = (raw_value, push_ts, lf, push_order)
            
            # FA WRITE line (farming)
            fm = FA_WRITE_RE.search(line)
            if fm:
                row_num = int(fm.group(1))
                day_num = fm.group(2)
                value = fm.group(3)
                eval_idx = row_num  # FA WRITE already uses 0-indexed
                col_name = f'Hedge Day {day_num}'
                
                if col_name in ALL_TRACKED_COLS:
                    key = (eval_idx, col_name)
                    client_cells[current_client][key] = (f'${value}', push_ts, lf, push_order)


# ============================================================
# STEP 2: Summary of what we found
# ============================================================
print(f"\n{'='*80}")
print(f"EXTRACTION SUMMARY")
print(f"{'='*80}")

clients_with_data = {c for c in client_cells if client_cells[c]}
print(f"Clients with session match data: {len(clients_with_data)}")
total_cells = sum(len(v) for v in client_cells.values())
print(f"Total cell values extracted: {total_cells}")

# ============================================================
# STEP 3: Connect to DB, compare and fill
# ============================================================
def _match_client_name(log_name, db_clients):
    """Match a log push name to a DB client_id. Tries exact, case-insensitive, first-word, etc."""
    if log_name in db_clients:
        return log_name
    # Case-insensitive
    for cid in db_clients:
        if cid.lower() == log_name.lower():
            return cid
    # First word match (e.g. "Chris Ream" -> "Chris")
    first = log_name.split()[0] if log_name.split() else log_name
    matches = [cid for cid in db_clients if cid.lower() == first.lower()]
    if len(matches) == 1:
        return matches[0]
    # DB first word matches log first word
    for cid in db_clients:
        cfirst = cid.split()[0]
        if cfirst.lower() == first.lower():
            return cid
    return None

print(f"\n{'='*80}")
print(f"DATABASE COMPARISON")
print(f"{'='*80}")

db = sqlite3.connect(DB_PATH)

# Get all client_ids from DB
db_clients = {}
for row in db.execute("SELECT client_id FROM clients_data").fetchall():
    db_clients[row[0]] = True

print(f"Clients in database: {len(db_clients)}")

# For each client with log data, compare
total_fills = 0
total_skipped_match = 0
total_skipped_existing = 0
total_no_db = 0
clients_processed = 0

for client_name in sorted(clients_with_data):
    cells = client_cells[client_name]
    if not cells:
        continue
    
    # Find matching client_id in DB
    # Log names are full ("Chris Ream") but DB may use short names ("Chris")
    client_id = _match_client_name(client_name, db_clients)
    if not client_id:
        print(f"\n  [SKIP] {client_name}: NOT FOUND in DB")
        total_no_db += 1
        continue
    
    # Load evaluations
    row = db.execute("SELECT evaluations FROM clients_data WHERE client_id=?", (client_id,)).fetchone()
    if not row or not row[0]:
        print(f"\n  [SKIP] {client_id}: No evaluations in DB")
        continue
    
    try:
        evals = json.loads(row[0])
    except:
        print(f"\n  [SKIP] {client_id}: Failed to parse evaluations JSON")
        continue
    
    # Compare each cell from logs with DB
    fills = []  # (eval_idx, col, log_value, db_value)
    matches = []
    existing_different = []
    out_of_range = []
    
    for (eval_idx, col_name), (log_value, ts, lf, order) in cells.items():
        if eval_idx >= len(evals):
            out_of_range.append((eval_idx, col_name, log_value))
            continue
        
        ev = evals[eval_idx]
        db_value = str(ev.get(col_name, '')).strip()
        
        # Clean log value for comparison
        log_clean = log_value.strip().lstrip('$')
        db_clean = db_value.strip().lstrip('$')
        
        # Is DB cell empty?
        if not db_clean or db_clean == 'nan' or db_clean == 'None':
            # Empty in DB, we have data from logs — FILL IT
            fills.append((eval_idx, col_name, log_value, db_value, ts))
        else:
            # DB has a value — check if it matches
            try:
                log_num = float(log_clean.replace(',', ''))
                db_num = float(db_clean.replace(',', ''))
                if abs(log_num - db_num) < 0.5:
                    matches.append((eval_idx, col_name))
                else:
                    existing_different.append((eval_idx, col_name, log_value, db_value))
            except:
                if log_clean == db_clean:
                    matches.append((eval_idx, col_name))
                else:
                    existing_different.append((eval_idx, col_name, log_value, db_value))
    
    clients_processed += 1
    total_fills += len(fills)
    total_skipped_match += len(matches)
    total_skipped_existing += len(existing_different)
    
    # Print summary for this client
    pushes = client_push_count.get(client_name, 0)
    errors = client_errors.get(client_name, 0)
    dates = sorted(client_push_dates.get(client_name, []))
    date_range = f"{dates[0]} to {dates[-1]}" if dates else 'N/A'
    
    status_icon = '✅' if fills else '🟢'
    if fills:
        status_icon = '🔧'
    
    print(f"\n  {status_icon} {client_id}: {pushes} pushes ({date_range}), {len(evals)} evals")
    print(f"     Log cells: {len(cells)} | Matches: {len(matches)} | "
          f"Fills needed: {len(fills)} | Already different: {len(existing_different)} | "
          f"Out of range: {len(out_of_range)}")
    
    if fills:
        # Export CSV for this client
        csv_path = os.path.join(OUTPUT_DIR, f'{client_id}_recovery.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
            writer = csv.writer(cf)
            writer.writerow(['Eval Index', 'Column', 'Log Value', 'DB Value (was empty)', 'Log Timestamp'])
            for eval_idx, col_name, log_value, db_value, ts in sorted(fills):
                writer.writerow([eval_idx, col_name, log_value, db_value, ts])
        
        # Show first few fills
        for eval_idx, col_name, log_value, db_value, ts in sorted(fills)[:5]:
            acct = str(evals[eval_idx].get('Account #', ''))[:25]
            print(f"       Row {eval_idx}: {col_name} = {log_value} (acct={acct}) [{ts}]")
        if len(fills) > 5:
            print(f"       ... and {len(fills) - 5} more (see {csv_path})")
        
        # Apply to DB if not dry run
        if not DRY_RUN:
            for eval_idx, col_name, log_value, db_value, ts in fills:
                evals[eval_idx][col_name] = log_value
            
            db.execute("UPDATE clients_data SET evaluations=? WHERE client_id=?",
                       (json.dumps(evals), client_id))
            db.commit()
            print(f"     ✅ Applied {len(fills)} fills to DB")
    
    if existing_different and len(existing_different) <= 5:
        print(f"     ℹ️  Different values (DB kept, not overwritten):")
        for eval_idx, col_name, log_val, db_val in existing_different[:3]:
            print(f"       Row {eval_idx}: {col_name} DB='{db_val}' vs Log='{log_val}'")

# ============================================================
# STEP 4: Final summary
# ============================================================
print(f"\n{'='*80}")
print(f"FINAL SUMMARY")
print(f"{'='*80}")
print(f"Clients processed: {clients_processed}")
print(f"Clients not in DB: {total_no_db}")
print(f"Total cells from logs: {total_cells}")
print(f"  - Already matching DB: {total_skipped_match}")
print(f"  - DB has different value (kept): {total_skipped_existing}")
print(f"  - Empty in DB, filled from logs: {total_fills}")
if DRY_RUN:
    print(f"\n⚡ This was a DRY RUN. To apply changes, run with --apply")
    print(f"   python recover_from_logs.py --apply")
    if SINGLE_CLIENT:
        print(f"   python recover_from_logs.py --apply --client \"{SINGLE_CLIENT}\"")
else:
    print(f"\n✅ All changes applied to database.")

db.close()
