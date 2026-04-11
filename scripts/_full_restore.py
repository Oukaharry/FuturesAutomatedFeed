#!/usr/bin/env python3
"""
Full restore from the 48GB NFS ghost DB.
Also tries to find the WAL data through the process that still has it open.

Run: python3 _full_restore.py
"""
import os, sys, json, sqlite3, glob, subprocess
from datetime import datetime

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
SOURCE_DB  = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')
SOURCE_WAL = SOURCE_DB + '-wal'
SOURCE_SHM = SOURCE_DB + '-shm'
CURRENT_DB = os.path.join(DASH_DIR, 'dashboard.db')

print("=" * 100)
print("FULL RESTORE FROM 48GB DB")
print(f"Time: {datetime.now()}")
print("=" * 100)


# ═══════════════════════════════════════════════════════════════
# STEP 0: Check if the process holding the file open still has the WAL
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("STEP 0: Find the process holding the NFS file open")
print(f"{'='*80}")

source_basename = os.path.basename(SOURCE_DB)
print(f"  Looking for processes with '{source_basename}' open...")

# Check /proc for open file descriptors pointing to this file
try:
    # Find which PIDs have this file open
    result = subprocess.run(['fuser', SOURCE_DB], capture_output=True, text=True, timeout=10)
    pids = result.stdout.strip().split()
    print(f"  fuser result: {result.stdout.strip()} (stderr: {result.stderr.strip()})")
    
    if not pids:
        # Try lsof
        result = subprocess.run(['lsof', SOURCE_DB], capture_output=True, text=True, timeout=10)
        print(f"  lsof result:\n{result.stdout[:2000]}")
except Exception as e:
    print(f"  fuser/lsof not available: {e}")

# Check /proc/*/fd for WAL file descriptors
print(f"\n  Checking /proc/*/fd for WAL files...")
wal_found = False
try:
    for pid_dir in glob.glob('/proc/[0-9]*/fd'):
        pid = pid_dir.split('/')[2]
        try:
            for fd in os.listdir(pid_dir):
                try:
                    link = os.readlink(os.path.join(pid_dir, fd))
                    if source_basename in link:
                        print(f"    PID {pid}, fd {fd} -> {link}")
                        if 'wal' in link.lower():
                            wal_found = True
                            wal_fd_path = os.path.join(pid_dir, fd)
                            # Try to read data from this fd
                            try:
                                size = os.path.getsize(wal_fd_path)
                                print(f"      *** WAL fd size: {size} bytes ***")
                                if size > 0:
                                    print(f"      *** WAL HAS DATA! Copying... ***")
                                    os.system(f"cp /proc/{pid}/fd/{fd} {DASH_DIR}/recovered_wal.dat")
                                    print(f"      Saved to {DASH_DIR}/recovered_wal.dat")
                            except Exception as e2:
                                print(f"      Cannot stat fd: {e2}")
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
except Exception as e:
    print(f"  /proc scan error: {e}")

if not wal_found:
    print(f"  No WAL file descriptor found in /proc")


# Also check if there's a regular WAL file for dashboard.db
print(f"\n  Checking for any WAL files in dashboard dir...")
for f in os.listdir(DASH_DIR):
    if 'wal' in f.lower() or 'journal' in f.lower():
        path = os.path.join(DASH_DIR, f)
        size = os.path.getsize(path)
        print(f"    {f}: {size} bytes")


# ═══════════════════════════════════════════════════════════════
# STEP 1: Try reading with WAL mode to see if process WAL is used 
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("STEP 1: Try connecting in WAL mode (not immutable)")
print(f"{'='*80}")

# Try normal connection — if the process WAL is accessible, we'll see fresh data
try:
    # Try read-only without immutable — may pick up WAL
    conn = sqlite3.connect(f'file:{SOURCE_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("""
        SELECT client_id, last_updated
        FROM clients_data 
        ORDER BY last_updated DESC LIMIT 10
    """).fetchall()
    
    print(f"  Read-only mode — latest last_updated dates:")
    for r in rows:
        print(f"    {r['last_updated']} | {r['client_id']}")
    
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  Journal mode: {journal_mode}")
    
    conn.close()
except Exception as e:
    print(f"  Read-only failed: {e}")
    print(f"  (This is expected if the file is locked)")


# ═══════════════════════════════════════════════════════════════
# STEP 2: Full data extraction from 48GB DB (immutable mode)
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("STEP 2: Full data extraction from 48GB DB")
print(f"{'='*80}")

try:
    conn = sqlite3.connect(f'file:{SOURCE_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    # Get all tables
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_data = {}
    
    for tbl in [t[0] for t in tables]:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()]
            print(f"  {tbl}: {cnt} rows, {len(cols)} cols ✓")
            table_data[tbl] = {'count': cnt, 'cols': cols, 'status': 'ok'}
        except sqlite3.DatabaseError as e:
            print(f"  {tbl}: CORRUPT ({e})")
            table_data[tbl] = {'count': 0, 'status': 'corrupt'}
    
    # Extract clients_data
    source_clients = {}
    rows = conn.execute("SELECT * FROM clients_data").fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients_data)").fetchall()]
    
    print(f"\n  clients_data: {len(rows)} rows extracted")
    for r in rows:
        d = dict(r)
        source_clients[d['client_id']] = d
    
    # Show date distribution
    print(f"\n  last_updated distribution (source 48GB):")
    dist = conn.execute("""
        SELECT SUBSTR(last_updated, 1, 10) as day, COUNT(*) 
        FROM clients_data GROUP BY day ORDER BY day DESC
    """).fetchall()
    for r in dist:
        print(f"    {r[0]}: {r[1]} clients")
    
    # Extract audit_log
    try:
        audit_rows = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 50").fetchall()
        print(f"\n  audit_log: latest 50 entries:")
        for r in audit_rows[:20]:
            print(f"    {r['timestamp']} | {r['action']} | {r['user_identifier']} | {r['details'][:80] if r['details'] else ''}")
    except Exception as e:
        print(f"\n  audit_log error: {e}")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# STEP 3: Compare with current DB
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("STEP 3: Compare 48GB vs Current DB")
print(f"{'='*80}")

cur_conn = sqlite3.connect(CURRENT_DB)
cur_conn.row_factory = sqlite3.Row
cur_rows = cur_conn.execute("SELECT * FROM clients_data").fetchall()
cur_cols = [r[1] for r in cur_conn.execute("PRAGMA table_info(clients_data)").fetchall()]

current_clients = {}
for r in cur_rows:
    d = dict(r)
    current_clients[d['client_id']] = d

print(f"\n  Source (48GB): {len(source_clients)} clients")
print(f"  Current DB:    {len(current_clients)} clients")

# Categorize
only_source = set(source_clients.keys()) - set(current_clients.keys())
only_current = set(current_clients.keys()) - set(source_clients.keys())
both = set(source_clients.keys()) & set(current_clients.keys())

if only_source:
    print(f"\n  ONLY in source (missing from current): {len(only_source)}")
    for cid in sorted(only_source):
        lu = source_clients[cid].get('last_updated', '?')
        print(f"    {cid:<40} last_updated={lu}")

if only_current:
    print(f"\n  ONLY in current (not in source): {len(only_current)}")
    for cid in sorted(only_current):
        lu = current_clients[cid].get('last_updated', '?')
        print(f"    {cid:<40} last_updated={lu}")

# For shared clients, compare data sizes
print(f"\n  Shared clients: {len(both)}")
source_bigger = []
current_bigger = []
same = []

compare_cols = [c for c in cols if c not in ('id', 'client_id', 'last_updated')]

for cid in sorted(both):
    src = source_clients[cid]
    cur = current_clients[cid]
    
    src_total = sum(len(str(src.get(c, '') or '')) for c in compare_cols)
    cur_total = sum(len(str(cur.get(c, '') or '')) for c in compare_cols)
    
    src_lu = src.get('last_updated', '')
    cur_lu = cur.get('last_updated', '')
    
    if src_total > cur_total + 100:  # Source has significantly more data
        source_bigger.append((cid, src_lu, cur_lu, src_total, cur_total))
    elif cur_total > src_total + 100:
        current_bigger.append((cid, src_lu, cur_lu, src_total, cur_total))
    else:
        same.append(cid)

print(f"    Same data: {len(same)}")
print(f"    Source has MORE data: {len(source_bigger)}")
print(f"    Current has MORE data: {len(current_bigger)}")

if source_bigger:
    print(f"\n    Source has MORE data (should restore):")
    for cid, slu, clu, st, ct in source_bigger:
        print(f"      {cid:<40} src_updated={slu} cur_updated={clu} src_size={st} cur_size={ct} delta=+{st-ct}")

if current_bigger:
    print(f"\n    Current has MORE data (keep current):")
    for cid, slu, clu, st, ct in current_bigger:
        print(f"      {cid:<40} src_updated={slu} cur_updated={clu} src_size={st} cur_size={ct}")


# ═══════════════════════════════════════════════════════════════
# STEP 4: AUTO-RESTORE anything the source has that current doesn't
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("STEP 4: AUTO-RESTORE")
print(f"{'='*80}")

# Backup first
backup_name = f"dashboard.db.pre_full_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
backup_path = os.path.join(DASH_DIR, backup_name)
import shutil
shutil.copy2(CURRENT_DB, backup_path)
print(f"  Backup: {backup_name} ({os.path.getsize(backup_path)/1024/1024:.1f} MB)")

# Common columns between source and current
common_cols = [c for c in cols if c in cur_cols and c != 'id']
print(f"  Common columns: {common_cols}")

restored = 0
updated = 0

# Restore clients only in source
for cid in only_source:
    src = source_clients[cid]
    placeholders = ', '.join(['?'] * len(common_cols))
    col_names = ', '.join(common_cols)
    values = [src.get(c) for c in common_cols]
    
    cur_conn.execute(f"INSERT INTO clients_data ({col_names}) VALUES ({placeholders})", values)
    print(f"  RESTORED: {cid} (last_updated={src.get('last_updated', '?')})")
    restored += 1

# Restore where source has more data
for cid, slu, clu, st, ct in source_bigger:
    src = source_clients[cid]
    set_clause = ', '.join([f"{c} = ?" for c in common_cols if c != 'client_id'])
    values = [src.get(c) for c in common_cols if c != 'client_id']
    values.append(cid)
    
    cur_conn.execute(f"UPDATE clients_data SET {set_clause} WHERE client_id = ?", values)
    print(f"  UPDATED: {cid} (src_updated={slu}, had +{st-ct} bytes more data)")
    updated += 1

cur_conn.commit()
cur_conn.close()

print(f"\n  SUMMARY:")
print(f"    Restored (new clients): {restored}")
print(f"    Updated (more data):    {updated}")
print(f"    Unchanged:              {len(same) + len(current_bigger)}")
print(f"    Current DB size: {os.path.getsize(CURRENT_DB)/1024/1024:.1f} MB")


print(f"\n{'='*100}")
print("DONE")
print(f"{'='*100}")
