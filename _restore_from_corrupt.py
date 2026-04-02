#!/usr/bin/env python3
"""
RESTORE DATA from 48GB corrupt DB (accessible via immutable=1 mode).
Compares every client's data between corrupt DB and current DB,
and restores any fresher records.

Also scans the 19.7GB rollback journal for recoverable April 2 data.

Run on PythonAnywhere: python3 _restore_from_corrupt.py
"""
import os, sys, json, sqlite3, re
from datetime import datetime, date
from copy import deepcopy

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB     = os.path.join(DASH_DIR, 'dashboard.db')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')  # 48GB, immutable works
JOURNAL    = os.path.join(DASH_DIR, '.nfs00000000048053f600025d72')   # 19.7GB journal

TIMESTAMP  = datetime.now().strftime('%Y%m%d_%H%M%S')

def connect_corrupt():
    """Connect to the 48GB corrupt DB in immutable mode."""
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def connect_current():
    """Connect to the current working DB."""
    conn = sqlite3.connect(CUR_DB)
    conn.row_factory = sqlite3.Row
    return conn

def safe_json(blob):
    """Try to parse JSON, return None on failure."""
    if blob is None:
        return None
    try:
        if isinstance(blob, bytes):
            blob = blob.decode('utf-8', errors='replace')
        return json.loads(blob)
    except:
        return None

def count_evaluations(data):
    """Count evaluations in a client_data blob."""
    if not data:
        return 0
    evals = data.get('evaluations', [])
    if isinstance(evals, list):
        return len(evals)
    return 0

def get_latest_date(data):
    """Find the most recent date in evaluations."""
    if not data:
        return None
    evals = data.get('evaluations', [])
    if not isinstance(evals, list):
        return None
    
    latest = None
    for ev in evals:
        if not isinstance(ev, dict):
            continue
        for key in ['Date Purchased', 'Date Started', 'Date Ended']:
            val = ev.get(key, '')
            if not val or val == 'null':
                continue
            # Try to parse various date formats
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%dT%H:%M:%S']:
                try:
                    d = datetime.strptime(str(val).strip(), fmt).date()
                    if latest is None or d > latest:
                        latest = d
                    break
                except:
                    continue
    return latest

def get_day_references(data):
    """Find day-of-week references (MONDAY, TUESDAY, etc.) in evaluations — indicates freshness."""
    if not data:
        return set()
    evals = data.get('evaluations', [])
    if not isinstance(evals, list):
        return set()
    
    days = set()
    days_pattern = re.compile(r'(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)', re.I)
    for ev in evals:
        if not isinstance(ev, dict):
            continue
        text = json.dumps(ev)
        found = days_pattern.findall(text)
        days.update(f.upper() for f in found)
    return days


# ══════════════════════════════════════════════════════════════════
# PHASE 1: FULL COMPARISON — corrupt DB vs current DB
# ══════════════════════════════════════════════════════════════════
print("=" * 90)
print("PHASE 1: COMPARE ALL CLIENT DATA — corrupt 48GB DB vs current DB")
print(f"Time: {datetime.now()}")
print("=" * 90)

try:
    corrupt_conn = connect_corrupt()
    current_conn = connect_current()
except Exception as e:
    print(f"FATAL: Cannot connect — {e}")
    sys.exit(1)

# Get all clients from corrupt DB
try:
    corrupt_clients = {}
    rows = corrupt_conn.execute("SELECT client_id, data FROM clients_data").fetchall()
    for row in rows:
        cid = row['client_id']
        data = safe_json(row['data'])
        corrupt_clients[cid] = data
    print(f"Corrupt DB: {len(corrupt_clients)} clients loaded")
except Exception as e:
    print(f"Error reading corrupt clients_data: {e}")
    # Try row by row
    corrupt_clients = {}
    try:
        cids = corrupt_conn.execute("SELECT rowid, client_id FROM clients_data").fetchall()
        for r in cids:
            try:
                row = corrupt_conn.execute("SELECT data FROM clients_data WHERE rowid=?", (r['rowid'],)).fetchone()
                data = safe_json(row['data']) if row else None
                corrupt_clients[r['client_id']] = data
            except Exception as e2:
                print(f"  Skip rowid {r['rowid']} ({r['client_id']}): {e2}")
                corrupt_clients[r['client_id']] = None
        print(f"Corrupt DB: {len(corrupt_clients)} clients (row-by-row recovery)")
    except Exception as e3:
        print(f"FATAL: Cannot read any client data from corrupt DB: {e3}")

# Get all clients from current DB
current_clients = {}
rows = current_conn.execute("SELECT client_id, data FROM clients_data").fetchall()
for row in rows:
    cid = row['client_id']
    data = safe_json(row['data'])
    current_clients[cid] = data
print(f"Current DB:  {len(current_clients)} clients loaded")

# Compare
print(f"\n{'Client':<30} {'Corrupt Evals':>14} {'Current Evals':>14} {'Corrupt Latest':>16} {'Current Latest':>16} {'Winner':>10}")
print("-" * 110)

fresher_in_corrupt = []
fresher_in_current = []
same = []
only_corrupt = []
only_current = []
corrupt_has_data_current_empty = []

all_clients = set(corrupt_clients.keys()) | set(current_clients.keys())

for cid in sorted(all_clients):
    c_data = corrupt_clients.get(cid)
    cur_data = current_clients.get(cid)
    
    c_evals = count_evaluations(c_data)
    cur_evals = count_evaluations(cur_data)
    c_latest = get_latest_date(c_data)
    cur_latest = get_latest_date(cur_data)
    
    if cid not in current_clients:
        winner = "CORRUPT*"
        only_corrupt.append(cid)
    elif cid not in corrupt_clients:
        winner = "CURRENT*"
        only_current.append(cid)
    elif c_data is None and cur_data is None:
        winner = "BOTH NULL"
        same.append(cid)
    elif c_data is None:
        winner = "CURRENT"
        fresher_in_current.append(cid)
    elif cur_data is None:
        winner = "CORRUPT!"
        corrupt_has_data_current_empty.append(cid)
    elif c_evals > cur_evals:
        winner = "CORRUPT!"
        fresher_in_corrupt.append(cid)
    elif cur_evals > c_evals:
        winner = "CURRENT"
        fresher_in_current.append(cid)
    elif c_latest and cur_latest and c_latest > cur_latest:
        winner = "CORRUPT!"
        fresher_in_corrupt.append(cid)
    elif c_latest and cur_latest and cur_latest > c_latest:
        winner = "CURRENT"
        fresher_in_current.append(cid)
    else:
        # Check day references as tiebreaker
        c_days = get_day_references(c_data)
        cur_days = get_day_references(cur_data)
        if c_days != cur_days:
            winner = "DIFFER"
            # If data is different at all, prefer the one with more content
            c_size = len(json.dumps(c_data)) if c_data else 0
            cur_size = len(json.dumps(cur_data)) if cur_data else 0
            if c_size > cur_size * 1.05:  # 5% more data
                winner = "CORRUPT?"
                fresher_in_corrupt.append(cid)
            elif cur_size > c_size * 1.05:
                winner = "CURRENT?"
                fresher_in_current.append(cid)
            else:
                same.append(cid)
        else:
            winner = "SAME"
            same.append(cid)
    
    # Only print if there's a notable difference
    if 'CORRUPT' in winner or cid in only_corrupt or cid in corrupt_has_data_current_empty:
        print(f"{cid:<30} {c_evals:>14} {cur_evals:>14} {str(c_latest):>16} {str(cur_latest):>16} {winner:>10}")

print(f"\n{'─'*90}")
print(f"SUMMARY:")
print(f"  Fresher in corrupt DB:  {len(fresher_in_corrupt)} clients")
print(f"  Fresher in current DB:  {len(fresher_in_current)} clients")
print(f"  Same data:              {len(same)} clients")
print(f"  Only in corrupt DB:     {len(only_corrupt)} — {only_corrupt}")
print(f"  Only in current DB:     {len(only_current)} — {only_current}")
print(f"  Corrupt has data, current empty: {len(corrupt_has_data_current_empty)} — {corrupt_has_data_current_empty}")

# Print ALL lines where corrupt is fresher, including those close
if fresher_in_corrupt or corrupt_has_data_current_empty:
    print(f"\n{'═'*90}")
    print("CLIENTS WHERE CORRUPT DB HAS FRESHER/MORE DATA:")
    print(f"{'═'*90}")
    for cid in fresher_in_corrupt + corrupt_has_data_current_empty:
        c_data = corrupt_clients.get(cid)
        cur_data = current_clients.get(cid)
        c_evals = count_evaluations(c_data)
        cur_evals = count_evaluations(cur_data)
        c_latest = get_latest_date(c_data)
        cur_latest = get_latest_date(cur_data)
        c_days = get_day_references(c_data)
        cur_days = get_day_references(cur_data)
        
        print(f"\n  {cid}:")
        print(f"    Evals: corrupt={c_evals}, current={cur_evals}")
        print(f"    Latest date: corrupt={c_latest}, current={cur_latest}")
        print(f"    Day refs: corrupt={c_days}, current={cur_days}")


# ══════════════════════════════════════════════════════════════════
# PHASE 2: CHECK ALL OTHER TABLES
# ══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*90}")
print("PHASE 2: COMPARE ALL TABLE ROW COUNTS")
print(f"{'='*90}")

tables_to_check = [
    'audit_log', 'evaluations', 'data_history', 'daily_watermarks',
    'cell_notes', 'waterlog_periods', 'kyc_links', 'quality_scan_results',
    'daily_checklists', 'system_settings', 'user_credentials',
    'api_keys', 'admin_passwords', 'phase_definitions'
]

table_diffs = {}
for table in tables_to_check:
    try:
        c_count = corrupt_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception as e:
        c_count = f"ERR: {e}"
    
    try:
        cur_count = current_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception as e:
        cur_count = f"ERR: {e}"
    
    status = ""
    if isinstance(c_count, int) and isinstance(cur_count, int):
        if c_count > cur_count:
            status = f"  <-- CORRUPT HAS {c_count - cur_count} MORE"
            table_diffs[table] = c_count - cur_count
        elif cur_count > c_count:
            status = f"  --> CURRENT HAS {cur_count - c_count} MORE"
    
    print(f"  {table:<25}  corrupt={str(c_count):>10}  current={str(cur_count):>10}{status}")


# ══════════════════════════════════════════════════════════════════
# PHASE 3: CHECK AUDIT LOG FOR TODAY
# ══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*90}")
print("PHASE 3: TODAY'S AUDIT LOG FROM CORRUPT DB")
print(f"{'='*90}")

try:
    rows = corrupt_conn.execute("""
        SELECT timestamp, action, client_id, details 
        FROM audit_log 
        WHERE timestamp LIKE '2026-04-02%' OR timestamp LIKE '2026-04-01%'
        ORDER BY timestamp DESC
    """).fetchall()
    print(f"  Found {len(rows)} audit entries for Apr 1-2")
    for r in rows[:50]:
        det = str(r['details'])[:80] if r['details'] else ''
        print(f"    {r['timestamp']} | {r['action']:<25} | {r['client_id'] or '':<25} | {det}")
except Exception as e:
    print(f"  Error: {e}")


# ══════════════════════════════════════════════════════════════════
# PHASE 4: CHECK data_history FOR RECENT SNAPSHOTS 
# ══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*90}")
print("PHASE 4: RECENT DATA_HISTORY SNAPSHOTS")
print(f"{'='*90}")

try:
    rows = corrupt_conn.execute("""
        SELECT client_id, timestamp, LENGTH(data) as data_len 
        FROM data_history 
        WHERE timestamp LIKE '2026-04%' OR timestamp LIKE '2026-03-3%'
        ORDER BY timestamp DESC LIMIT 30
    """).fetchall()
    print(f"  Found {len(rows)} recent snapshots")
    for r in rows:
        print(f"    {r['timestamp']} | {r['client_id']:<25} | {r['data_len']} bytes")
except Exception as e:
    print(f"  Error: {e}")


# ══════════════════════════════════════════════════════════════════
# PHASE 5: EXTRACT APRIL 2 DATA FROM JOURNAL (raw scan)
# ══════════════════════════════════════════════════════════════════
if os.path.exists(JOURNAL):
    print(f"\n\n{'='*90}")
    print("PHASE 5: DEEP SCAN OF ROLLBACK JOURNAL FOR APRIL 2 DATA")
    print(f"{'='*90}")
    
    # The journal file structure:
    # Header: 8 bytes magic + 4 bytes page count + 4 bytes random nonce + 
    #         4 bytes initial pages + 4 bytes sector size + 4 bytes page size
    # Then series of: 4 bytes page number + page_size bytes of page data + 4 bytes checksum
    
    import struct
    
    try:
        with open(JOURNAL, 'rb') as f:
            header = f.read(28)
        
        magic = header[0:8]
        page_count = struct.unpack('>i', header[8:12])[0]
        nonce = struct.unpack('>I', header[12:16])[0]
        initial_pages = struct.unpack('>I', header[16:20])[0]
        sector_size = struct.unpack('>I', header[20:24])[0]
        page_size = struct.unpack('>I', header[24:28])[0]
        
        print(f"  Journal header:")
        print(f"    Page count: {page_count}")
        print(f"    Page size: {page_size}")
        print(f"    Sector size: {sector_size}")
        print(f"    Initial DB pages: {initial_pages}")
        
        if page_size < 512 or page_size > 65536:
            print(f"  WARNING: unusual page size, trying 4096...")
            page_size = 4096
        
        fsize = os.path.getsize(JOURNAL)
        # Each journal entry: 4 bytes page_num + page_size bytes data + 4 bytes checksum
        entry_size = 4 + page_size + 4
        
        # Start after header (sector-aligned)
        start_offset = sector_size if sector_size >= 512 else 512
        est_entries = (fsize - start_offset) // entry_size
        print(f"  Estimated journal entries: {est_entries}")
        
        # Scan journal pages for today's data
        today_pages = []
        recent_pages = []
        client_data_pages = []
        
        with open(JOURNAL, 'rb') as f:
            f.seek(start_offset)
            
            scan_limit = min(fsize, 5 * 1024 * 1024 * 1024)  # First 5GB
            entries_scanned = 0
            
            while f.tell() < scan_limit:
                try:
                    # Read page number
                    pn_raw = f.read(4)
                    if len(pn_raw) < 4:
                        break
                    page_num = struct.unpack('>I', pn_raw)[0]
                    
                    # Read page data
                    page_data = f.read(page_size)
                    if len(page_data) < page_size:
                        break
                    
                    # Read checksum
                    cksum = f.read(4)
                    
                    entries_scanned += 1
                    
                    # Check page for today's data
                    if b'04/02/2026' in page_data or b'2026-04-02' in page_data:
                        today_pages.append({
                            'page_num': page_num,
                            'offset': f.tell() - entry_size,
                            'snippet': page_data[:500].decode('utf-8', errors='replace').replace('\x00', '')
                        })
                    elif b'04/01/2026' in page_data or b'2026-04-01' in page_data:
                        recent_pages.append({
                            'page_num': page_num,
                            'offset': f.tell() - entry_size,
                        })
                    
                    # Check for client data blobs
                    if b'"evaluations"' in page_data and b'"identity"' in page_data:
                        client_data_pages.append({
                            'page_num': page_num,
                            'offset': f.tell() - entry_size,
                        })
                    
                    if entries_scanned % 100000 == 0:
                        pct = f.tell() / scan_limit * 100
                        print(f"    Scanned {entries_scanned} entries ({pct:.1f}%) — today={len(today_pages)}, recent={len(recent_pages)}, client_blobs={len(client_data_pages)}")
                
                except Exception as e:
                    # Skip bad entry
                    entries_scanned += 1
                    continue
        
        print(f"\n  Journal scan complete:")
        print(f"    Entries scanned: {entries_scanned}")
        print(f"    Pages with April 2 data: {len(today_pages)}")
        print(f"    Pages with April 1 data: {len(recent_pages)}")
        print(f"    Pages with client data blobs: {len(client_data_pages)}")
        
        if today_pages:
            print(f"\n  APRIL 2 DATA FOUND IN JOURNAL:")
            for pg in today_pages[:20]:
                print(f"    Page {pg['page_num']}, offset {pg['offset']}:")
                print(f"      {pg['snippet'][:300]}")
    
    except Exception as e:
        print(f"  Error scanning journal: {e}")
        import traceback
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════
# PHASE 6: AUTO-RESTORE (if corrupt has fresher data)
# ══════════════════════════════════════════════════════════════════
if fresher_in_corrupt or corrupt_has_data_current_empty or only_corrupt:
    print(f"\n\n{'='*90}")
    print("PHASE 6: READY TO RESTORE — PREVIEW")
    print(f"{'='*90}")
    
    restore_candidates = fresher_in_corrupt + corrupt_has_data_current_empty
    print(f"  {len(restore_candidates)} clients have fresher data in corrupt DB")
    print(f"  {len(only_corrupt)} clients exist only in corrupt DB")
    
    # Create restore SQL file
    restore_path = os.path.expanduser(f'~/MT5Dashboard/_restore_data_{TIMESTAMP}.sql')
    count = 0
    
    with open(restore_path, 'w') as f:
        f.write(f"-- AUTO-RESTORE from corrupt DB\n")
        f.write(f"-- Generated: {datetime.now()}\n")
        f.write(f"-- Backup current DB first!\n\n")
        
        for cid in restore_candidates:
            c_data = corrupt_clients.get(cid)
            if c_data is None:
                continue
            data_json = json.dumps(c_data)
            # Escape single quotes for SQL
            data_escaped = data_json.replace("'", "''")
            f.write(f"-- {cid}: corrupt has {count_evaluations(c_data)} evals, latest={get_latest_date(c_data)}\n")
            f.write(f"UPDATE clients_data SET data = '{data_escaped}' WHERE client_id = '{cid}';\n\n")
            count += 1
        
        for cid in only_corrupt:
            c_data = corrupt_clients.get(cid)
            if c_data is None:
                continue
            data_json = json.dumps(c_data)
            data_escaped = data_json.replace("'", "''")
            f.write(f"-- {cid}: only in corrupt DB, {count_evaluations(c_data)} evals\n")
            f.write(f"INSERT OR IGNORE INTO clients_data (client_id, data) VALUES ('{cid}', '{data_escaped}');\n\n")
            count += 1
    
    if count > 0:
        print(f"\n  *** RESTORE FILE CREATED: {restore_path}")
        print(f"  *** Contains {count} UPDATE/INSERT statements")
        print(f"\n  To apply:")
        print(f"    1. cp dashboard/dashboard.db dashboard/dashboard.db.pre_restore_{TIMESTAMP}")
        print(f"    2. sqlite3 dashboard/dashboard.db < _restore_data_{TIMESTAMP}.sql")
    else:
        print(f"\n  No data to restore — current DB is already up to date")

# Also check: dump ALL other tables that have MORE rows in corrupt
if table_diffs:
    print(f"\n\n{'='*90}")
    print("TABLES WITH MORE DATA IN CORRUPT DB:")
    print(f"{'='*90}")
    
    for table, diff in table_diffs.items():
        print(f"\n  {table}: corrupt has {diff} more rows")
        
        if table == 'audit_log':
            # Find the extra audit entries
            try:
                # Get max rowid in current
                cur_max = current_conn.execute("SELECT MAX(rowid) FROM audit_log").fetchone()[0] or 0
                extra = corrupt_conn.execute(f"SELECT timestamp, action, client_id FROM audit_log WHERE rowid > ? ORDER BY rowid LIMIT 20", (cur_max,)).fetchall()
                for r in extra:
                    print(f"    {r['timestamp']} | {r['action']} | {r['client_id'] or ''}")
            except Exception as e:
                print(f"    Error: {e}")
        
        elif table in ('evaluations', 'daily_watermarks', 'cell_notes', 'data_history'):
            try:
                cur_max = current_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
                c_max = corrupt_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
                print(f"    Current max rowid: {cur_max}, Corrupt max rowid: {c_max}")
            except Exception as e:
                print(f"    Error: {e}")


corrupt_conn.close()
current_conn.close()

print(f"\n\n{'='*90}")
print("RESTORE ANALYSIS COMPLETE")
print(f"{'='*90}")
