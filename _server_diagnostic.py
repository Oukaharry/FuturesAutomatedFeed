#!/usr/bin/env python3
"""
Server diagnostic: check KYC links, find recoverable data sources,
and determine exact crash timeline from audit_log.
Run on PythonAnywhere: python3 _server_diagnostic.py
"""
import sqlite3, os, glob, json
from datetime import datetime

DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB   = os.path.join(DASH_DIR, 'dashboard.db')

print("=" * 80)
print("1. ALL FILES IN dashboard/ DIRECTORY (potential data sources)")
print("=" * 80)
for f in sorted(os.listdir(DASH_DIR)):
    fp = os.path.join(DASH_DIR, f)
    if os.path.isfile(fp):
        sz = os.path.getsize(fp)
        if sz > 1024*1024:
            print(f"  {f:50s}  {sz/1024/1024:.1f} MB")
        elif sz > 1024:
            print(f"  {f:50s}  {sz/1024:.1f} KB")
        else:
            print(f"  {f:50s}  {sz} B")

# Also check for WAL/SHM/journal files that might still exist
for pattern in ['*.db-wal', '*.db-shm', '*.db-journal', '*.db.bak', '*.sqlite*', '.nfs*', '*.corrupt*', '*.old*', '*.backup*']:
    matches = glob.glob(os.path.join(DASH_DIR, pattern))
    for m in matches:
        sz = os.path.getsize(m)
        print(f"  [FOUND] {os.path.basename(m):45s}  {sz/1024/1024:.1f} MB")

# Check parent directory too
parent = os.path.expanduser('~/MT5Dashboard')
print(f"\nLarge files in {parent}:")
for f in os.listdir(parent):
    fp = os.path.join(parent, f)
    if os.path.isfile(fp) and os.path.getsize(fp) > 1024*1024:
        print(f"  {f:50s}  {os.path.getsize(fp)/1024/1024:.1f} MB")

# ── 2. CHECK kyc_links TABLE ──────────────────────────────────────
print("\n" + "=" * 80)
print("2. KYC LINKS TABLE IN CURRENT DB")
print("=" * 80)
try:
    conn = sqlite3.connect(f'file:{CUR_DB}?mode=ro', uri=True)
    rows = conn.execute("SELECT * FROM kyc_links").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM kyc_links LIMIT 0").description]
    print(f"  Columns: {cols}")
    print(f"  Row count: {len(rows)}")
    if rows:
        for r in rows:
            print(f"    {r}")
    else:
        print("  >> TABLE IS EMPTY - KYC links were lost!")
    conn.close()
except Exception as e:
    print(f"  ERROR reading kyc_links: {e}")

# ── 3. CHECK kyc_links IN OLD CORRUPT DB ──────────────────────────
print("\n" + "=" * 80)
print("3. KYC LINKS IN OLD/BACKUP DB FILES")
print("=" * 80)
old_files = []
for f in os.listdir(DASH_DIR):
    fp = os.path.join(DASH_DIR, f)
    if os.path.isfile(fp) and f != 'dashboard.db' and os.path.getsize(fp) > 100000:
        old_files.append(fp)
# Check parent too
for f in os.listdir(parent):
    fp = os.path.join(parent, f)
    if os.path.isfile(fp) and fp.endswith(('.db', '.sqlite', '.sqlite3')) and os.path.getsize(fp) > 100000:
        old_files.append(fp)
# Also try .nfs files
for f in os.listdir(DASH_DIR):
    if f.startswith('.nfs'):
        old_files.append(os.path.join(DASH_DIR, f))

for fp in old_files:
    fn = os.path.basename(fp)
    print(f"\n  Checking {fn}...")
    try:
        c = sqlite3.connect(f'file:{fp}?mode=ro', uri=True)
        rows = c.execute("SELECT * FROM kyc_links").fetchall()
        print(f"    kyc_links rows: {len(rows)}")
        for r in rows:
            print(f"      {r}")
        c.close()
    except Exception as e:
        print(f"    Error: {e}")

# ── 4. CRASH TIMELINE FROM AUDIT LOG ──────────────────────────────
print("\n" + "=" * 80)
print("4. CRASH TIMELINE (from audit_log)")
print("=" * 80)
try:
    conn = sqlite3.connect(f'file:{CUR_DB}?mode=ro', uri=True)
    
    # Get today's date
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = datetime.now().strftime('%Y-%m-%d')  # Will check both
    
    # Find the gap - last entry before crash and first after
    print(f"\n  Last 30 audit_log entries (most recent first):")
    rows = conn.execute("""
        SELECT timestamp, action, details 
        FROM audit_log 
        ORDER BY timestamp DESC 
        LIMIT 30
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}  |  {r[1]:30s}  |  {str(r[2])[:60]}")
    
    # Look for gaps > 1 hour today
    print(f"\n  Looking for time gaps > 30 min in audit_log (last 200 entries):")
    rows = conn.execute("""
        SELECT timestamp FROM audit_log 
        ORDER BY timestamp DESC 
        LIMIT 200
    """).fetchall()
    
    prev = None
    for r in rows:
        try:
            ts = r[0]
            # Try multiple formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                try:
                    dt = datetime.strptime(ts, fmt)
                    break
                except:
                    continue
            else:
                continue
            
            if prev is not None:
                gap = (prev - dt).total_seconds()
                if gap > 1800:  # > 30 min gap
                    print(f"    GAP: {gap/3600:.1f} hours between {ts} and {prev.strftime('%Y-%m-%d %H:%M:%S')}")
            prev = dt
        except Exception as e:
            pass
    
    # Count entries by date
    print(f"\n  Entries per date (last 7 days):")
    rows = conn.execute("""
        SELECT DATE(timestamp) as d, COUNT(*) as c 
        FROM audit_log 
        GROUP BY d 
        ORDER BY d DESC 
        LIMIT 7
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}: {r[1]} entries")
    
    # Show CLIENT_DATA_PUSH entries specifically  
    print(f"\n  Recent CLIENT_DATA_PUSH entries:")
    rows = conn.execute("""
        SELECT timestamp, action, details 
        FROM audit_log 
        WHERE action = 'CLIENT_DATA_PUSH'
        ORDER BY timestamp DESC 
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}  |  {str(r[2])[:80]}")
    
    # Check if there's a DB_INIT or similar entry
    print(f"\n  DB init / repair / startup entries:")
    rows = conn.execute("""
        SELECT timestamp, action, details 
        FROM audit_log 
        WHERE action LIKE '%INIT%' OR action LIKE '%REPAIR%' OR action LIKE '%START%' OR action LIKE '%RESET%'
        ORDER BY timestamp DESC 
        LIMIT 10
    """).fetchall()
    if rows:
        for r in rows:
            print(f"    {r[0]}  |  {r[1]}  |  {str(r[2])[:60]}")
    else:
        print("    (none found)")
    
    conn.close()
except Exception as e:
    print(f"  ERROR: {e}")

# ── 5. CHECK clients_data FRESHNESS ──────────────────────────────
print("\n" + "=" * 80)
print("5. clients_data LAST UPDATE TIMESTAMPS")
print("=" * 80)
try:
    conn = sqlite3.connect(f'file:{CUR_DB}?mode=ro', uri=True)
    rows = conn.execute("SELECT client_id, statistics FROM clients_data").fetchall()
    for r in rows[:10]:  # First 10
        cid = r[0]
        try:
            stats = json.loads(r[1]) if r[1] else {}
            # Look for any timestamp fields
            ts_fields = {}
            def find_timestamps(d, prefix=''):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if isinstance(v, str) and ('2026' in v or '2025' in v):
                            ts_fields[prefix+k] = v
                        elif isinstance(v, dict):
                            find_timestamps(v, prefix+k+'.')
            find_timestamps(stats)
            if ts_fields:
                print(f"  {cid}: {ts_fields}")
        except:
            pass
    conn.close()
except Exception as e:
    print(f"  ERROR: {e}")

# ── 6. CHECK FOR ANY RECOVERABLE FILES ANYWHERE ──────────────────
print("\n" + "=" * 80)
print("6. SEARCHING FOR ANY .db/.sqlite FILES IN HOME")
print("=" * 80)
home = os.path.expanduser('~')
for root, dirs, files in os.walk(home):
    # Skip .local, .cache etc
    dirs[:] = [d for d in dirs if not d.startswith('.') or d == '.nfs']
    for f in files:
        if any(f.endswith(ext) for ext in ['.db', '.sqlite', '.sqlite3']) or f.startswith('.nfs'):
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
                if sz > 10000:  # > 10KB
                    print(f"  {fp}  ({sz/1024/1024:.1f} MB)")
            except:
                pass

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
