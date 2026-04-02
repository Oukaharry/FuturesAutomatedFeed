#!/usr/bin/env python3
"""
RESTORE DATA from 48GB corrupt DB (accessible via immutable=1 mode).
Compares every client's data between corrupt DB and current DB,
and restores any fresher records.

Also scans the 19.7GB rollback journal for recoverable April 2 data.

Run on PythonAnywhere: python3 _restore_from_corrupt.py
"""
import os, sys, json, sqlite3, re, struct, shutil
from datetime import datetime, date

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB     = os.path.join(DASH_DIR, 'dashboard.db')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')  # 48GB, immutable works
JOURNAL    = os.path.join(DASH_DIR, '.nfs00000000048053f600025d72')   # 19.7GB journal

TIMESTAMP  = datetime.now().strftime('%Y%m%d_%H%M%S')

# All data columns in clients_data (excluding id, client_id, last_updated)
DATA_COLS = [
    'deals', 'positions', 'account', 'evaluations', 'statistics',
    'dropdown_options', 'identity', 'hedge_accounts', 'prop_accounts',
    'vps_accounts', 'payment_info', 'payment_address'
]
ALL_COLS = ['client_id'] + DATA_COLS + ['last_updated']

def connect_corrupt():
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def connect_current():
    conn = sqlite3.connect(CUR_DB)
    conn.row_factory = sqlite3.Row
    return conn

def safe_json(blob):
    if blob is None:
        return None
    try:
        if isinstance(blob, bytes):
            blob = blob.decode('utf-8', errors='replace')
        return json.loads(blob)
    except:
        return blob

def count_evals(row):
    if not row:
        return 0
    try:
        raw = row['evaluations']
    except (IndexError, KeyError):
        return 0
    lst = safe_json(raw)
    if isinstance(lst, list):
        return len(lst)
    return 0

def get_latest_date(row):
    if not row:
        return None
    try:
        raw = row['evaluations']
    except (IndexError, KeyError):
        return None
    evals = safe_json(raw)
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
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%dT%H:%M:%S']:
                try:
                    d = datetime.strptime(str(val).strip(), fmt).date()
                    if latest is None or d > latest:
                        latest = d
                    break
                except:
                    continue
    return latest

def data_size(row):
    if not row:
        return 0
    total = 0
    for col in DATA_COLS:
        try:
            val = row[col]
            if val:
                total += len(str(val))
        except (IndexError, KeyError):
            pass
    return total

def get_columns(conn, table):
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cursor.fetchall()]
    except:
        return []


# ══════════════════════════════════════════════════════════════════
# PHASE 0: DISCOVER SCHEMA
# ══════════════════════════════════════════════════════════════════
print("=" * 90)
print("PHASE 0: DISCOVER TABLE SCHEMAS")
print("=" * 90)

try:
    corrupt_conn = connect_corrupt()
    current_conn = connect_current()
except Exception as e:
    print(f"FATAL: Cannot connect — {e}")
    sys.exit(1)

corrupt_cols = get_columns(corrupt_conn, 'clients_data')
current_cols = get_columns(current_conn, 'clients_data')
print(f"  Corrupt DB columns: {corrupt_cols}")
print(f"  Current DB columns: {current_cols}")

common_cols = [c for c in ALL_COLS if c in corrupt_cols and c in current_cols]
common_data_cols = [c for c in DATA_COLS if c in corrupt_cols and c in current_cols]
print(f"  Common columns: {common_cols}")

sel_cols = ', '.join(common_cols)


# ══════════════════════════════════════════════════════════════════
# PHASE 1: FULL COMPARISON
# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("PHASE 1: COMPARE ALL CLIENT DATA — corrupt 48GB DB vs current DB")
print(f"Time: {datetime.now()}")
print("=" * 90)

corrupt_clients = {}
try:
    rows = corrupt_conn.execute(f"SELECT {sel_cols} FROM clients_data").fetchall()
    for row in rows:
        corrupt_clients[row['client_id']] = row
    print(f"Corrupt DB: {len(corrupt_clients)} clients loaded")
except Exception as e:
    print(f"Error reading corrupt clients_data in bulk: {e}")
    try:
        cids = corrupt_conn.execute("SELECT rowid, client_id FROM clients_data").fetchall()
        for r in cids:
            try:
                row = corrupt_conn.execute(f"SELECT {sel_cols} FROM clients_data WHERE rowid=?", (r['rowid'],)).fetchone()
                if row:
                    corrupt_clients[r['client_id']] = row
            except Exception as e2:
                print(f"  Skip rowid {r['rowid']} ({r['client_id']}): {e2}")
        print(f"Corrupt DB: {len(corrupt_clients)} clients (row-by-row recovery)")
    except Exception as e3:
        print(f"FATAL: Cannot read client data: {e3}")
        sys.exit(1)

current_clients = {}
rows = current_conn.execute(f"SELECT {sel_cols} FROM clients_data").fetchall()
for row in rows:
    current_clients[row['client_id']] = row
print(f"Current DB:  {len(current_clients)} clients loaded")

print(f"\n{'Client':<30} {'C.Evals':>8} {'Cur.Evals':>10} {'C.Latest':>12} {'Cur.Latest':>12} {'C.Size':>10} {'Cur.Size':>10} {'Winner':>10}")
print("-" * 112)

fresher_in_corrupt = []
fresher_in_current = []
same = []
only_corrupt = []
only_current = []

all_cids = sorted(set(corrupt_clients.keys()) | set(current_clients.keys()))

for cid in all_cids:
    c_row = corrupt_clients.get(cid)
    cur_row = current_clients.get(cid)
    
    c_ev = count_evals(c_row)
    cur_ev = count_evals(cur_row)
    c_date = get_latest_date(c_row)
    cur_date = get_latest_date(cur_row)
    c_sz = data_size(c_row)
    cur_sz = data_size(cur_row)
    
    if cid not in current_clients:
        winner = "CORRUPT*"
        only_corrupt.append(cid)
    elif cid not in corrupt_clients:
        winner = "CURRENT*"
        only_current.append(cid)
    elif c_ev > cur_ev:
        winner = "CORRUPT!"
        fresher_in_corrupt.append(cid)
    elif cur_ev > c_ev:
        winner = "CURRENT"
        fresher_in_current.append(cid)
    elif c_date and cur_date and c_date > cur_date:
        winner = "CORRUPT!"
        fresher_in_corrupt.append(cid)
    elif c_date and cur_date and cur_date > c_date:
        winner = "CURRENT"
        fresher_in_current.append(cid)
    elif c_sz > cur_sz * 1.05:
        winner = "CORRUPT?"
        fresher_in_corrupt.append(cid)
    elif cur_sz > c_sz * 1.05:
        winner = "CURRENT?"
        fresher_in_current.append(cid)
    else:
        winner = "SAME"
        same.append(cid)
    
    flag = " <<<" if "CORRUPT" in winner else ""
    print(f"{cid:<30} {c_ev:>8} {cur_ev:>10} {str(c_date or '-'):>12} {str(cur_date or '-'):>12} {c_sz:>10} {cur_sz:>10} {winner:>10}{flag}")

print(f"\n{'─'*90}")
print(f"SUMMARY:")
print(f"  Fresher in corrupt DB:     {len(fresher_in_corrupt)} clients  {fresher_in_corrupt}")
print(f"  Fresher in current DB:     {len(fresher_in_current)} clients")
print(f"  Same data:                 {len(same)} clients")
print(f"  Only in corrupt DB:        {len(only_corrupt)} — {only_corrupt}")
print(f"  Only in current DB:        {len(only_current)} — {only_current}")

if fresher_in_corrupt or only_corrupt:
    print(f"\n{'═'*90}")
    print("DETAIL: CLIENTS WHERE CORRUPT DB HAS MORE/FRESHER DATA")
    print(f"{'═'*90}")
    for cid in fresher_in_corrupt + only_corrupt:
        c_row = corrupt_clients.get(cid)
        cur_row = current_clients.get(cid)
        print(f"\n  ── {cid} ──")
        print(f"    Corrupt: evals={count_evals(c_row)}, latest={get_latest_date(c_row)}, size={data_size(c_row)}")
        print(f"    Current: evals={count_evals(cur_row)}, latest={get_latest_date(cur_row)}, size={data_size(cur_row)}")
        for col in common_data_cols:
            try:
                c_val = c_row[col] if c_row else None
            except:
                c_val = None
            try:
                cur_val = cur_row[col] if cur_row else None
            except:
                cur_val = None
            c_len = len(str(c_val)) if c_val else 0
            cur_len = len(str(cur_val)) if cur_val else 0
            if c_len != cur_len:
                print(f"    {col}: corrupt={c_len} chars, current={cur_len} chars {'<<<' if c_len > cur_len else ''}")


# ══════════════════════════════════════════════════════════════════
# PHASE 2: TABLE ROW COUNTS
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
    except:
        c_count = "ERR"
    try:
        cur_count = current_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except:
        cur_count = "ERR"
    
    status = ""
    if isinstance(c_count, int) and isinstance(cur_count, int):
        if c_count > cur_count:
            status = f"  <-- CORRUPT HAS {c_count - cur_count} MORE"
            table_diffs[table] = c_count - cur_count
        elif cur_count > c_count:
            status = f"  --> CURRENT HAS {cur_count - c_count} MORE"
    
    print(f"  {table:<25}  corrupt={str(c_count):>10}  current={str(cur_count):>10}{status}")


# ══════════════════════════════════════════════════════════════════
# PHASE 3: TODAY'S AUDIT LOG
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
# PHASE 4: RECENT DATA_HISTORY
# ══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*90}")
print("PHASE 4: RECENT DATA_HISTORY SNAPSHOTS FROM CORRUPT DB")
print(f"{'='*90}")

dh_cols_corrupt = get_columns(corrupt_conn, 'data_history')
dh_cols_current = get_columns(current_conn, 'data_history')
print(f"  data_history columns (corrupt): {dh_cols_corrupt}")
print(f"  data_history columns (current): {dh_cols_current}")

try:
    rows = corrupt_conn.execute("""
        SELECT * FROM data_history 
        WHERE timestamp LIKE '2026-04%' OR timestamp LIKE '2026-03-3%'
        ORDER BY timestamp DESC LIMIT 30
    """).fetchall()
    print(f"  Found {len(rows)} recent data_history snapshots in corrupt DB")
    for r in rows:
        cols_info = {k: (len(str(r[k])) if r[k] else 0) for k in r.keys() if k not in ('id',)}
        print(f"    {cols_info}")
except Exception as e:
    print(f"  Error: {e}")


# ══════════════════════════════════════════════════════════════════
# PHASE 5: SCAN ROLLBACK JOURNAL
# ══════════════════════════════════════════════════════════════════
if os.path.exists(JOURNAL):
    print(f"\n\n{'='*90}")
    print("PHASE 5: DEEP SCAN OF ROLLBACK JOURNAL FOR APRIL 2 DATA")
    print(f"{'='*90}")
    
    try:
        with open(JOURNAL, 'rb') as f:
            header = f.read(28)
        
        page_count = struct.unpack('>i', header[8:12])[0]
        initial_pages = struct.unpack('>I', header[16:20])[0]
        sector_size = struct.unpack('>I', header[20:24])[0]
        page_size = struct.unpack('>I', header[24:28])[0]
        
        print(f"  Journal: page_count={page_count}, page_size={page_size}, sector_size={sector_size}")
        
        if page_size < 512 or page_size > 65536:
            print(f"  WARNING: unusual page size {page_size}, using 4096")
            page_size = 4096
        
        fsize = os.path.getsize(JOURNAL)
        entry_size = 4 + page_size + 4
        start_offset = max(sector_size, 512)
        est_entries = (fsize - start_offset) // entry_size
        print(f"  Estimated journal entries: {est_entries}")
        
        today_pages = []
        
        with open(JOURNAL, 'rb') as f:
            f.seek(start_offset)
            scan_limit = min(fsize, 5 * 1024 * 1024 * 1024)
            entries_scanned = 0
            
            while f.tell() < scan_limit:
                try:
                    pn_raw = f.read(4)
                    if len(pn_raw) < 4:
                        break
                    page_num = struct.unpack('>I', pn_raw)[0]
                    page_data = f.read(page_size)
                    if len(page_data) < page_size:
                        break
                    f.read(4)  # checksum
                    entries_scanned += 1
                    
                    if b'04/02/2026' in page_data or b'2026-04-02' in page_data:
                        snippet = page_data.decode('utf-8', errors='replace').replace('\x00', '')
                        today_pages.append({
                            'page_num': page_num,
                            'snippet': snippet[:600]
                        })
                    
                    if entries_scanned % 100000 == 0:
                        pct = f.tell() / scan_limit * 100
                        print(f"    Scanned {entries_scanned} entries ({pct:.1f}%) — today={len(today_pages)}")
                except:
                    entries_scanned += 1
                    continue
        
        print(f"\n  Journal scan: {entries_scanned} entries, {len(today_pages)} with April 2 data")
        
        if today_pages:
            print(f"\n  APRIL 2 DATA IN JOURNAL:")
            for pg in today_pages[:20]:
                print(f"    Page {pg['page_num']}:")
                print(f"      {pg['snippet'][:400]}")
    
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════
# PHASE 6: AUTO-RESTORE
# ══════════════════════════════════════════════════════════════════
restore_candidates = fresher_in_corrupt + only_corrupt
if restore_candidates:
    print(f"\n\n{'='*90}")
    print("PHASE 6: AUTO-RESTORE FROM CORRUPT DB")
    print(f"{'='*90}")
    
    backup_path = f"{CUR_DB}.pre_restore_{TIMESTAMP}"
    print(f"  Creating backup: {backup_path}")
    shutil.copy2(CUR_DB, backup_path)
    print(f"  Backup created ({os.path.getsize(backup_path)/1024/1024:.1f} MB)")
    
    restored = 0
    errors = 0
    write_conn = sqlite3.connect(CUR_DB)
    
    for cid in restore_candidates:
        c_row = corrupt_clients.get(cid)
        if c_row is None:
            continue
        try:
            exists = write_conn.execute("SELECT 1 FROM clients_data WHERE client_id=?", (cid,)).fetchone()
            
            if exists:
                set_parts = []
                values = []
                for col in common_data_cols:
                    try:
                        val = c_row[col]
                        set_parts.append(f"{col} = ?")
                        values.append(val)
                    except (IndexError, KeyError):
                        pass
                if set_parts:
                    sql = f"UPDATE clients_data SET {', '.join(set_parts)} WHERE client_id = ?"
                    values.append(cid)
                    write_conn.execute(sql, values)
                    print(f"  UPDATED: {cid} — evals={count_evals(c_row)}, latest={get_latest_date(c_row)}")
                    restored += 1
            else:
                ins_cols = ['client_id']
                ins_vals = [cid]
                for col in common_data_cols:
                    try:
                        ins_cols.append(col)
                        ins_vals.append(c_row[col])
                    except (IndexError, KeyError):
                        pass
                try:
                    ins_cols.append('last_updated')
                    ins_vals.append(c_row['last_updated'])
                except:
                    ins_cols.append('last_updated')
                    ins_vals.append(datetime.now().isoformat())
                
                placeholders = ', '.join(['?'] * len(ins_cols))
                col_str = ', '.join(ins_cols)
                write_conn.execute(f"INSERT INTO clients_data ({col_str}) VALUES ({placeholders})", ins_vals)
                print(f"  INSERTED: {cid} — evals={count_evals(c_row)}, latest={get_latest_date(c_row)}")
                restored += 1
        except Exception as e:
            print(f"  ERROR restoring {cid}: {e}")
            errors += 1
    
    write_conn.commit()
    write_conn.close()
    print(f"\n  RESTORE COMPLETE: {restored} clients restored, {errors} errors")
    print(f"  Backup at: {backup_path}")
else:
    print(f"\n\n{'='*90}")
    print("PHASE 6: NO CLIENT RESTORE NEEDED")
    print(f"  Current DB already has equal or fresher data for all clients")
    print(f"{'='*90}")

# Restore extra rows from other tables
if table_diffs:
    print(f"\n\n{'='*90}")
    print("PHASE 7: RESTORE EXTRA ROWS FROM OTHER TABLES")
    print(f"{'='*90}")
    
    for table, diff in table_diffs.items():
        print(f"\n  {table}: corrupt has {diff} more rows")
        try:
            cur_max = current_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
            c_max = corrupt_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
            print(f"    Current max rowid: {cur_max}, Corrupt max rowid: {c_max}")
            
            if c_max > cur_max:
                c_tcols = get_columns(corrupt_conn, table)
                cur_tcols = get_columns(current_conn, table)
                shared = [c for c in c_tcols if c in cur_tcols and c not in ('id', 'rowid')]
                
                extra_rows = corrupt_conn.execute(
                    f"SELECT {', '.join(shared)} FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT 200",
                    (cur_max,)
                ).fetchall()
                
                print(f"    Found {len(extra_rows)} extra rows to restore")
                if extra_rows:
                    write_conn2 = sqlite3.connect(CUR_DB)
                    placeholders = ', '.join(['?'] * len(shared))
                    col_str = ', '.join(shared)
                    count = 0
                    for r in extra_rows:
                        try:
                            vals = [r[c] for c in shared]
                            write_conn2.execute(f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})", vals)
                            count += 1
                        except Exception as e:
                            if count < 3:
                                print(f"    Error: {e}")
                    write_conn2.commit()
                    write_conn2.close()
                    print(f"    Restored {count} rows to {table}")
                    for r in extra_rows[:5]:
                        sample = {k: (str(r[k])[:60] if r[k] else '') for k in shared[:4]}
                        print(f"      {sample}")
        except Exception as e:
            print(f"    Error: {e}")

corrupt_conn.close()
current_conn.close()

print(f"\n\n{'='*90}")
print("RESTORE ANALYSIS COMPLETE")
print(f"{'='*90}")
