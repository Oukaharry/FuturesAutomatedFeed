#!/usr/bin/env python3
"""
RESTORE YESTERDAY'S DATA from the 48GB deleted DB (.nfs file).
This DB contains the state from before today's corruption.

For each client, compares last_updated timestamps and data sizes
to pick the best version, then restores it.

Run: python3 _restore_yesterday.py
"""
import os, sys, json, sqlite3, shutil
from datetime import datetime

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB     = os.path.join(DASH_DIR, 'dashboard.db')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')  # 48GB deleted DB

TIMESTAMP  = datetime.now().strftime('%Y%m%d_%H%M%S')

DATA_COLS = [
    'deals', 'positions', 'account', 'evaluations', 'statistics',
    'dropdown_options', 'identity', 'hedge_accounts', 'prop_accounts',
    'vps_accounts', 'payment_info', 'payment_address'
]

def get_columns(conn, table):
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except:
        return []

def data_size(row, cols):
    total = 0
    for col in cols:
        try:
            val = row[col]
            if val:
                total += len(str(val))
        except:
            pass
    return total

def count_evals(row):
    try:
        raw = row['evaluations']
        if raw:
            lst = json.loads(raw)
            if isinstance(lst, list):
                return len(lst)
    except:
        pass
    return 0

print("=" * 100)
print("RESTORE YESTERDAY'S DATA FROM DELETED DB")
print(f"Time: {datetime.now()}")
print("=" * 100)

# Connect
print("\nConnecting to databases...")
try:
    old_conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    old_conn.row_factory = sqlite3.Row
    old_conn.execute("SELECT COUNT(*) FROM clients_data")
    print(f"  Deleted DB (48GB): OK")
except Exception as e:
    print(f"  FATAL: Cannot connect to deleted DB: {e}")
    sys.exit(1)

cur_conn = sqlite3.connect(CUR_DB)
cur_conn.row_factory = sqlite3.Row
print(f"  Current DB: OK")

# Find common columns
old_cols = get_columns(old_conn, 'clients_data')
cur_cols = get_columns(cur_conn, 'clients_data')
common_data = [c for c in DATA_COLS if c in old_cols and c in cur_cols]
print(f"\n  Deleted DB columns: {old_cols}")
print(f"  Current DB columns: {cur_cols}")
print(f"  Common data cols:   {common_data}")

# ═══════════════════════════════════════════════════════════════
# STEP 1: Compare last_updated timestamps
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("STEP 1: COMPARE last_updated TIMESTAMPS")
print(f"{'='*100}")

old_rows = {}
for r in old_conn.execute("SELECT * FROM clients_data").fetchall():
    old_rows[r['client_id']] = r

cur_rows = {}
for r in cur_conn.execute("SELECT * FROM clients_data").fetchall():
    cur_rows[r['client_id']] = r

print(f"\nDeleted DB: {len(old_rows)} clients")
print(f"Current DB: {len(cur_rows)} clients")

print(f"\n{'Client':<30} {'Deleted last_updated':<28} {'Current last_updated':<28} {'Del.Evals':>10} {'Cur.Evals':>10} {'Del.Size':>10} {'Cur.Size':>10} {'Action':<12}")
print("-" * 148)

to_restore = []     # Clients where deleted DB has better data
to_insert = []      # Clients only in deleted DB
already_better = [] # Current DB already better
same = []

all_cids = sorted(set(old_rows.keys()) | set(cur_rows.keys()))

for cid in all_cids:
    old = old_rows.get(cid)
    cur = cur_rows.get(cid)
    
    old_lu = old['last_updated'] if old else '-'
    cur_lu = cur['last_updated'] if cur else '-'
    old_ev = count_evals(old) if old else 0
    cur_ev = count_evals(cur) if cur else 0
    old_sz = data_size(old, common_data) if old else 0
    cur_sz = data_size(cur, common_data) if cur else 0
    
    if not cur:
        action = "INSERT"
        to_insert.append(cid)
    elif not old:
        action = "KEEP-CUR"
        already_better.append(cid)
    else:
        # Both exist — compare
        # Priority: more evaluations > more data > newer last_updated
        if old_ev > cur_ev:
            action = "RESTORE"
            to_restore.append(cid)
        elif cur_ev > old_ev:
            action = "KEEP-CUR"
            already_better.append(cid)
        elif old_sz > cur_sz + 50:  # Deleted has meaningfully more data
            action = "RESTORE"
            to_restore.append(cid)
        elif cur_sz > old_sz + 50:
            action = "KEEP-CUR"
            already_better.append(cid)
        elif str(old_lu) > str(cur_lu):
            action = "RESTORE"
            to_restore.append(cid)
        elif str(cur_lu) > str(old_lu):
            action = "KEEP-CUR"
            already_better.append(cid)
        else:
            action = "SAME"
            same.append(cid)
    
    flag = " <<<" if action in ("RESTORE", "INSERT") else ""
    print(f"{cid:<30} {str(old_lu):<28} {str(cur_lu):<28} {old_ev:>10} {cur_ev:>10} {old_sz:>10} {cur_sz:>10} {action:<12}{flag}")

print(f"\n{'─'*100}")
print(f"SUMMARY:")
print(f"  RESTORE from deleted DB: {len(to_restore)} clients")
print(f"  INSERT from deleted DB:  {len(to_insert)} clients")
print(f"  Keep current (better):   {len(already_better)} clients")
print(f"  Same data:               {len(same)} clients")

if to_restore:
    print(f"\n  Clients to RESTORE: {to_restore}")
if to_insert:
    print(f"  Clients to INSERT:  {to_insert}")

# ═══════════════════════════════════════════════════════════════
# STEP 2: BACKUP AND RESTORE
# ═══════════════════════════════════════════════════════════════
restore_total = to_restore + to_insert

if not restore_total:
    print(f"\n{'='*100}")
    print("NO RESTORE NEEDED — current DB already has equal or better data for all clients")
    print(f"{'='*100}")
else:
    print(f"\n{'='*100}")
    print(f"STEP 2: RESTORING {len(restore_total)} CLIENTS")
    print(f"{'='*100}")
    
    # Backup first
    backup_path = f"{CUR_DB}.pre_restore_{TIMESTAMP}"
    print(f"\n  Creating backup: {os.path.basename(backup_path)}")
    shutil.copy2(CUR_DB, backup_path)
    print(f"  Backup: {os.path.getsize(backup_path)/1024/1024:.1f} MB")
    
    write_conn = sqlite3.connect(CUR_DB)
    restored = 0
    inserted = 0
    errors = 0
    
    for cid in restore_total:
        old = old_rows.get(cid)
        if not old:
            continue
        
        try:
            exists = write_conn.execute("SELECT 1 FROM clients_data WHERE client_id=?", (cid,)).fetchone()
            
            if exists:
                # UPDATE
                set_parts = []
                values = []
                for col in common_data:
                    try:
                        set_parts.append(f"{col} = ?")
                        values.append(old[col])
                    except:
                        pass
                # Also restore last_updated
                try:
                    set_parts.append("last_updated = ?")
                    values.append(old['last_updated'])
                except:
                    pass
                
                if set_parts:
                    sql = f"UPDATE clients_data SET {', '.join(set_parts)} WHERE client_id = ?"
                    values.append(cid)
                    write_conn.execute(sql, values)
                    
                    old_ev = count_evals(old)
                    old_sz = data_size(old, common_data)
                    print(f"  RESTORED: {cid:<30} evals={old_ev}, size={old_sz}, last_updated={old['last_updated']}")
                    restored += 1
            else:
                # INSERT
                ins_cols = ['client_id']
                ins_vals = [cid]
                for col in common_data:
                    try:
                        ins_cols.append(col)
                        ins_vals.append(old[col])
                    except:
                        pass
                try:
                    ins_cols.append('last_updated')
                    ins_vals.append(old['last_updated'])
                except:
                    ins_cols.append('last_updated')
                    ins_vals.append(datetime.now().isoformat())
                
                placeholders = ', '.join(['?'] * len(ins_cols))
                col_str = ', '.join(ins_cols)
                write_conn.execute(f"INSERT INTO clients_data ({col_str}) VALUES ({placeholders})", ins_vals)
                
                old_ev = count_evals(old)
                print(f"  INSERTED: {cid:<30} evals={old_ev}, last_updated={old.get('last_updated', 'N/A')}")
                inserted += 1
                
        except Exception as e:
            print(f"  ERROR: {cid}: {e}")
            errors += 1
    
    write_conn.commit()
    write_conn.close()
    
    print(f"\n{'─'*100}")
    print(f"RESTORE COMPLETE:")
    print(f"  Updated:  {restored} clients")
    print(f"  Inserted: {inserted} clients")
    print(f"  Errors:   {errors}")
    print(f"  Backup:   {backup_path}")


# ═══════════════════════════════════════════════════════════════
# STEP 3: RESTORE OTHER TABLES (audit_log, cell_notes, etc.)
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 3: CHECK OTHER TABLES FOR EXTRA DATA IN DELETED DB")
print(f"{'='*100}")

other_tables = [
    'audit_log', 'daily_watermarks', 'cell_notes', 'waterlog_periods',
    'kyc_links', 'quality_scan_results', 'daily_checklists',
    'user_credentials', 'admin_passwords', 'system_settings'
]

for table in other_tables:
    try:
        old_count = old_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except:
        old_count = -1
    try:
        cur_count = cur_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except:
        cur_count = -1
    
    diff = ""
    if old_count > 0 and cur_count >= 0 and old_count > cur_count:
        diff = f"  <<< DELETED HAS {old_count - cur_count} MORE ROWS"
    
    if old_count >= 0 or cur_count >= 0:
        print(f"  {table:<25} deleted={old_count:>8}  current={cur_count:>8}{diff}")
    
    # Auto-restore if deleted has more
    if old_count > cur_count and old_count > 0 and cur_count >= 0:
        try:
            old_tcols = get_columns(old_conn, table)
            cur_tcols = get_columns(cur_conn, table)
            shared = [c for c in old_tcols if c in cur_tcols and c not in ('id', 'rowid')]
            
            if not shared:
                continue
            
            cur_max_rowid = cur_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
            old_max_rowid = old_conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] or 0
            
            if old_max_rowid > cur_max_rowid:
                extra = old_conn.execute(
                    f"SELECT {', '.join(shared)} FROM {table} WHERE rowid > ? ORDER BY rowid",
                    (cur_max_rowid,)
                ).fetchall()
                
                if extra:
                    write_conn3 = sqlite3.connect(CUR_DB)
                    placeholders = ', '.join(['?'] * len(shared))
                    col_str = ', '.join(shared)
                    count = 0
                    for r in extra:
                        try:
                            vals = [r[c] for c in shared]
                            write_conn3.execute(f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})", vals)
                            count += 1
                        except:
                            pass
                    write_conn3.commit()
                    write_conn3.close()
                    print(f"    -> Restored {count} extra rows to {table}")
        except Exception as e:
            print(f"    -> Error restoring {table}: {e}")


old_conn.close()
cur_conn.close()

# Final verification
print(f"\n\n{'='*100}")
print("FINAL VERIFICATION")
print(f"{'='*100}")

ver_conn = sqlite3.connect(CUR_DB)
ver_conn.row_factory = sqlite3.Row
total = ver_conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
print(f"  Total clients in current DB: {total}")

# Show last_updated distribution
dist = ver_conn.execute("""
    SELECT SUBSTR(last_updated, 1, 10) as day, COUNT(*) as cnt 
    FROM clients_data GROUP BY day ORDER BY day DESC
""").fetchall()
print(f"\n  last_updated distribution after restore:")
for r in dist:
    print(f"    {r['day']}: {r['cnt']} clients")

ver_conn.close()

print(f"\n  Current DB size: {os.path.getsize(CUR_DB)/1024/1024:.1f} MB")
print(f"\n{'='*100}")
print("DONE")
print(f"{'='*100}")
