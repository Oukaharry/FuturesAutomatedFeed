#!/usr/bin/env python3
"""
Find ALL SQLite databases on the server and check which has the freshest data.
Run on PythonAnywhere: python3 _find_all_dbs.py
"""
import os, sqlite3, json, glob
from datetime import datetime

home = os.path.expanduser('~')

print("=" * 90)
print("SEARCHING ENTIRE HOME DIRECTORY FOR SQLITE FILES")
print("=" * 90)

db_files = []

# Walk entire home directory including hidden files
for root, dirs, files in os.walk(home):
    # Skip deep .local/share, .cache etc but keep important ones
    skip = ['.cache', '.local/lib', '__pycache__', 'node_modules', '.npm']
    if any(s in root for s in skip):
        continue
    for f in files:
        fp = os.path.join(root, f)
        try:
            sz = os.path.getsize(fp)
            if sz < 1000:
                continue
            # Check by extension
            if any(f.endswith(ext) for ext in ['.db', '.sqlite', '.sqlite3', '.db3']):
                db_files.append(fp)
                continue
            # Check .nfs ghost files (could be deleted SQLite)
            if f.startswith('.nfs') and sz > 100000:
                db_files.append(fp)
                continue
            # Check files with 'dashboard', 'backup', 'corrupt', 'old', 'copy' in name
            fl = f.lower()
            if any(k in fl for k in ['dashboard', 'backup', 'corrupt', 'old_', 'copy', 'restored', 'rescue', 'recovered']):
                if sz > 100000:
                    db_files.append(fp)
                    continue
            # Check large files that might be SQLite (check magic bytes)
            if sz > 1024 * 1024:  # > 1MB
                try:
                    with open(fp, 'rb') as fh:
                        header = fh.read(16)
                        if header.startswith(b'SQLite format 3'):
                            db_files.append(fp)
                except:
                    pass
        except (PermissionError, OSError):
            pass

# Also check /tmp for any SQLite files
for tmpdir in ['/tmp', '/var/tmp']:
    try:
        for f in os.listdir(tmpdir):
            fp = os.path.join(tmpdir, f)
            try:
                if os.path.isfile(fp) and os.path.getsize(fp) > 100000:
                    with open(fp, 'rb') as fh:
                        if fh.read(16).startswith(b'SQLite format 3'):
                            db_files.append(fp)
            except:
                pass
    except:
        pass

# Also specifically check the dashboard directory for ANY file
dash_dir = os.path.join(home, 'MT5Dashboard', 'dashboard')
if os.path.isdir(dash_dir):
    for f in os.listdir(dash_dir):
        fp = os.path.join(dash_dir, f)
        if os.path.isfile(fp) and fp not in db_files:
            try:
                sz = os.path.getsize(fp)
                if sz > 100000:
                    with open(fp, 'rb') as fh:
                        if fh.read(16).startswith(b'SQLite format 3'):
                            db_files.append(fp)
            except:
                pass

# Also check MT5Dashboard root and one level up
for check_dir in [os.path.join(home, 'MT5Dashboard'), home]:
    if os.path.isdir(check_dir):
        for f in os.listdir(check_dir):
            fp = os.path.join(check_dir, f)
            if os.path.isfile(fp) and fp not in db_files:
                try:
                    sz = os.path.getsize(fp)
                    if sz > 100000:
                        with open(fp, 'rb') as fh:
                            if fh.read(16).startswith(b'SQLite format 3'):
                                db_files.append(fp)
                except:
                    pass

# Deduplicate
db_files = sorted(set(db_files))

print(f"\nFound {len(db_files)} SQLite database files:\n")

for fp in db_files:
    sz = os.path.getsize(fp)
    mtime = datetime.fromtimestamp(os.path.getmtime(fp))
    if sz > 1024*1024*1024:
        sz_str = f"{sz/1024/1024/1024:.1f} GB"
    elif sz > 1024*1024:
        sz_str = f"{sz/1024/1024:.1f} MB"
    else:
        sz_str = f"{sz/1024:.1f} KB"
    
    rel = fp.replace(home, '~')
    print(f"  {rel}")
    print(f"    Size: {sz_str}  |  Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Try to read table info and check data freshness
    try:
        conn = sqlite3.connect(f'file:{fp}?mode=ro', uri=True, timeout=5)
        
        # List tables
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"    Tables: {tables}")
        
        # Check clients_data count
        if 'clients_data' in tables:
            cnt = conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
            print(f"    clients_data rows: {cnt}")
            
            # Check freshness - look at audit_log last entry
            if 'audit_log' in tables:
                last = conn.execute("SELECT timestamp FROM audit_log ORDER BY timestamp DESC LIMIT 1").fetchone()
                if last:
                    print(f"    Last audit_log entry: {last[0]}")
                cnt_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
                print(f"    Total audit_log entries: {cnt_audit}")
                
                # Today's entries
                today = datetime.now().strftime('%Y-%m-%d')
                today_cnt = conn.execute("SELECT COUNT(*) FROM audit_log WHERE timestamp LIKE ?", (f"{today}%",)).fetchone()[0]
                print(f"    Today's audit entries: {today_cnt}")
            
            # Check evaluations freshness 
            row = conn.execute("SELECT client_id, evaluations FROM clients_data LIMIT 1").fetchone()
            if row and row[1]:
                try:
                    evals = json.loads(row[1])
                    if evals and isinstance(evals, list) and len(evals) > 0:
                        last_ev = evals[-1]
                        date_fields = {k: v for k, v in last_ev.items() if isinstance(v, str) and '2026' in v}
                        if date_fields:
                            print(f"    Sample eval dates ({row[0]}): {date_fields}")
                except:
                    pass
            
            # Check kyc_links
            if 'kyc_links' in tables:
                kyc_cnt = conn.execute("SELECT COUNT(*) FROM kyc_links").fetchone()[0]
                print(f"    kyc_links rows: {kyc_cnt}")
                if kyc_cnt > 0:
                    links = conn.execute("SELECT primary_client, linked_client FROM kyc_links").fetchall()
                    for l in links:
                        print(f"      {l[0]} -> {l[1]}")
        
        conn.close()
    except Exception as e:
        print(f"    Error reading: {e}")
    
    print()

# ── Also check WAL files ─────────────────────────────────────────
print("=" * 90)
print("CHECKING FOR WAL/SHM/JOURNAL FILES")
print("=" * 90)
for root, dirs, files in os.walk(home):
    skip = ['.cache', '.local/lib', '__pycache__']
    if any(s in root for s in skip):
        continue
    for f in files:
        if f.endswith(('-wal', '-shm', '-journal', '.db-wal', '.db-shm', '.db-journal')):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            print(f"  {fp.replace(home, '~')}  ({sz/1024:.1f} KB)")

# ── Check .nfs files specifically ────────────────────────────────
print("\n" + "=" * 90)
print("NFS GHOST FILES (deleted files still held open)")
print("=" * 90)
for root, dirs, files in os.walk(home):
    for f in files:
        if f.startswith('.nfs'):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            print(f"  {fp.replace(home, '~')}  ({sz/1024/1024:.1f} MB)  modified: {mtime}")

print("\n" + "=" * 90)
print("DONE - Look for the DB with the most recent audit_log timestamp")
print("=" * 90)
