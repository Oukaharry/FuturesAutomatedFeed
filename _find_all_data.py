#!/usr/bin/env python3
"""
COMPREHENSIVE SEARCH for ALL database files on the server.
Looks for any DB that has data from March 26 - April 1 (the missing week).

Also deep-scans the 19.7GB journal file for recoverable data.

Run: python3 _find_all_data.py
"""
import os, sys, json, sqlite3, struct, subprocess
from datetime import datetime

HOME = os.path.expanduser('~')
DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')

print("=" * 100)
print("COMPREHENSIVE SEARCH FOR ALL DATABASE FILES & MISSING WEEK DATA")
print(f"Time: {datetime.now()}")
print("=" * 100)

# ═══════════════════════════════════════════════════════════════
# STEP 1: Find ALL files that could be databases
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("STEP 1: FIND ALL POTENTIAL DATABASE FILES")
print(f"{'='*100}")

all_files = []

# Walk entire home directory
for root, dirs, files in os.walk(HOME):
    # Skip deep nested dirs
    depth = root.replace(HOME, '').count(os.sep)
    if depth > 5:
        continue
    # Skip virtualenvs and node_modules
    if '.virtualenvs' in root or 'node_modules' in root or '__pycache__' in root:
        continue
    
    for f in files:
        path = os.path.join(root, f)
        try:
            size = os.path.getsize(path)
        except:
            continue
        
        # Check if it could be a database
        is_candidate = False
        reason = ""
        
        if f.endswith(('.db', '.sqlite', '.sqlite3', '.db3')):
            is_candidate = True
            reason = "DB extension"
        elif f.endswith(('.db-wal', '.db-shm', '-wal', '-shm')):
            is_candidate = True
            reason = "WAL/SHM file"
        elif f.endswith(('.db-journal', '-journal')):
            is_candidate = True
            reason = "Journal file"
        elif '.backup' in f or '.bak' in f:
            is_candidate = True
            reason = "Backup file"
        elif f.startswith('.nfs'):
            is_candidate = True
            reason = "NFS ghost (deleted file still open)"
        elif f.endswith('.corrupt') or '.corrupt.' in f:
            is_candidate = True
            reason = "Corrupt marker"
        elif size > 1024 * 1024:  # >1MB files in dashboard dir
            if DASH_DIR in root:
                # Check if it's a SQLite file by header
                try:
                    with open(path, 'rb') as fh:
                        header = fh.read(16)
                    if header[:16] == b'SQLite format 3\x00':
                        is_candidate = True
                        reason = "SQLite header detected"
                    elif header[:8] == b'\xd9\xd5\x05\xf9\x20\xa1\x63\xd7':
                        is_candidate = True
                        reason = "Journal file (by header)"
                    elif header[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
                        is_candidate = True
                        reason = "WAL file (by header)"
                except:
                    pass
        
        if is_candidate:
            all_files.append((path, size, reason))

# Also check /tmp
for tmpdir in ['/tmp', '/var/tmp']:
    if os.path.exists(tmpdir):
        try:
            for f in os.listdir(tmpdir):
                path = os.path.join(tmpdir, f)
                try:
                    if os.path.isfile(path):
                        size = os.path.getsize(path)
                        if f.endswith('.db') or f.startswith('.nfs') or size > 10*1024*1024:
                            all_files.append((path, size, "In /tmp"))
                except:
                    pass
        except:
            pass

# Sort by size desc
all_files.sort(key=lambda x: -x[1])

print(f"\nFound {len(all_files)} candidate files:\n")
for path, size, reason in all_files:
    rel = path.replace(HOME + '/', '~/')
    if size > 1024*1024*1024:
        sz = f"{size/1024/1024/1024:.2f} GB"
    elif size > 1024*1024:
        sz = f"{size/1024/1024:.1f} MB"
    elif size > 1024:
        sz = f"{size/1024:.1f} KB"
    else:
        sz = f"{size} B"
    print(f"  {sz:>12}  {reason:<30}  {rel}")


# ═══════════════════════════════════════════════════════════════
# STEP 2: Check each file for data from the missing week
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 2: CHECK EACH FILE FOR MARCH 26 - APRIL 1 DATA")
print(f"{'='*100}")

MISSING_DATES = ['2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
                 '2026-03-30', '2026-03-31', '2026-04-01']
MISSING_DATES_ALT = ['03/26/2026', '03/27/2026', '03/28/2026', '03/29/2026',
                     '03/30/2026', '03/31/2026', '04/01/2026',
                     '3/26/2026', '3/27/2026', '3/28/2026', '3/29/2026',
                     '3/30/2026', '3/31/2026', '4/1/2026']

ALL_SEARCH = MISSING_DATES + MISSING_DATES_ALT

for path, size, reason in all_files:
    rel = path.replace(HOME + '/', '~/')
    sz_str = f"{size/1024/1024:.1f} MB" if size < 1024*1024*1024 else f"{size/1024/1024/1024:.2f} GB"
    
    print(f"\n  ── {rel} ({sz_str}) ──")
    
    # Try to open as SQLite
    opened = False
    for method_name, opener in [
        ('immutable', lambda p=path: sqlite3.connect(f'file:{p}?immutable=1', uri=True)),
        ('normal', lambda p=path: sqlite3.connect(p, timeout=10)),
    ]:
        try:
            conn = opener()
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if tables:
                print(f"    Opened as SQLite ({method_name}): {len(tables)} tables")
                opened = True
                
                # Check clients_data last_updated
                if 'clients_data' in tables:
                    try:
                        dist = conn.execute("""
                            SELECT SUBSTR(last_updated, 1, 10) as day, COUNT(*) as cnt 
                            FROM clients_data GROUP BY day ORDER BY day DESC
                        """).fetchall()
                        print(f"    last_updated distribution:")
                        for r in dist:
                            flag = " *** MISSING WEEK!" if r['day'] in MISSING_DATES else ""
                            print(f"      {r['day']}: {r['cnt']} clients{flag}")
                    except Exception as e:
                        print(f"    last_updated error: {e}")
                    
                    # Direct search in evaluations text
                    try:
                        rows = conn.execute("SELECT client_id, evaluations FROM clients_data").fetchall()
                        for d in MISSING_DATES:
                            db = d.encode() if isinstance(d, str) else d
                            hits = []
                            for r in rows:
                                ev = r['evaluations'] or ''
                                if d in ev:
                                    hits.append(r['client_id'])
                            if hits:
                                print(f"    *** {d} found in evaluations of: {hits}")
                    except Exception as e:
                        print(f"    evaluations search error: {e}")
                
                # Check audit_log
                if 'audit_log' in tables:
                    cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
                    time_col = next((c for c in ['timestamp', 'created_at', 'date'] if c in cols), None)
                    if time_col:
                        for d in MISSING_DATES:
                            try:
                                c = conn.execute(f"SELECT COUNT(*) FROM audit_log WHERE {time_col} LIKE ?", (f"{d}%",)).fetchone()[0]
                                if c > 0:
                                    print(f"    *** audit_log has {c} entries for {d}!")
                            except:
                                pass
                
                # Check data_history  
                if 'data_history' in tables:
                    cols = [r[1] for r in conn.execute("PRAGMA table_info(data_history)").fetchall()]
                    print(f"    data_history columns: {cols}")
                    # Try all possible time columns
                    for tc in cols:
                        for d in MISSING_DATES:
                            try:
                                c = conn.execute(f"SELECT COUNT(*) FROM data_history WHERE {tc} LIKE ?", (f"{d}%",)).fetchone()[0]
                                if c > 0:
                                    print(f"    *** data_history.{tc} has {c} entries for {d}!")
                            except:
                                pass
                
                conn.close()
                break
        except:
            try:
                conn.close()
            except:
                pass
            continue
    
    if not opened:
        # Raw byte scan for missing dates
        print(f"    Cannot open as SQLite — scanning raw bytes...")
        scan_limit = min(size, 5 * 1024 * 1024 * 1024)  # 5GB max
        found = {}
        
        try:
            with open(path, 'rb') as f:
                offset = 0
                chunk_size = 50 * 1024 * 1024  # 50MB
                while offset < scan_limit:
                    try:
                        f.seek(offset)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        
                        for d in ALL_SEARCH:
                            count = chunk.count(d.encode('utf-8'))
                            if count > 0:
                                found[d] = found.get(d, 0) + count
                        
                        offset += chunk_size
                        if offset % (1024 * 1024 * 1024) == 0:
                            print(f"      ...scanned {offset/1024/1024/1024:.0f} GB")
                    except:
                        offset += chunk_size
                        continue
        except Exception as e:
            print(f"    Raw scan error: {e}")
        
        if found:
            print(f"    RAW SCAN - dates found:")
            for d in sorted(found.keys()):
                flag = " *** MISSING WEEK!" if d in MISSING_DATES or d in MISSING_DATES_ALT else ""
                print(f"      {d}: {found[d]} occurrences{flag}")
        else:
            print(f"    No missing-week dates found in raw scan")


# ═══════════════════════════════════════════════════════════════
# STEP 3: Check current DB's audit_log for the missing week
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 3: AUDIT LOG ANALYSIS — what happened during the missing week?")
print(f"{'='*100}")

conn = sqlite3.connect(os.path.join(DASH_DIR, 'dashboard.db'))
conn.row_factory = sqlite3.Row
cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
print(f"  audit_log columns: {cols}")

# Get daily activity summary
print(f"\n  Daily audit_log summary (last 2 weeks):")
try:
    time_col = next((c for c in ['timestamp', 'created_at', 'date'] if c in cols), 'timestamp')
    action_col = next((c for c in ['action', 'event', 'type'] if c in cols), 'action')
    
    daily = conn.execute(f"""
        SELECT SUBSTR({time_col}, 1, 10) as day, COUNT(*) as cnt
        FROM audit_log
        WHERE {time_col} >= '2026-03-20'
        GROUP BY day ORDER BY day DESC
    """).fetchall()
    
    for r in daily:
        flag = " *** NO DATA PUSH?" if r['cnt'] < 10 else ""
        missing = " <-- MISSING WEEK" if r['day'] in MISSING_DATES else ""
        print(f"    {r['day']}: {r['cnt']:>6} entries{flag}{missing}")
    
    # For any missing-week dates found, show what actions happened
    for d in MISSING_DATES:
        try:
            actions = conn.execute(f"""
                SELECT {action_col}, COUNT(*) as cnt
                FROM audit_log WHERE {time_col} LIKE ?
                GROUP BY {action_col} ORDER BY cnt DESC
            """, (f"{d}%",)).fetchall()
            if actions:
                print(f"\n    Actions on {d}:")
                for a in actions:
                    print(f"      {a[0]}: {a[1]}")
        except:
            pass

except Exception as e:
    print(f"  Error: {e}")

conn.close()


# ═══════════════════════════════════════════════════════════════
# STEP 4: Deep scan the 19.7GB journal for missing week data
# ═══════════════════════════════════════════════════════════════
JOURNAL = os.path.join(DASH_DIR, '.nfs00000000048053f600025d72')
if os.path.exists(JOURNAL):
    print(f"\n\n{'='*100}")
    print("STEP 4: DEEP SCAN 19.7GB JOURNAL FOR MISSING WEEK DATA")
    print(f"{'='*100}")
    
    fsize = os.path.getsize(JOURNAL)
    print(f"  File size: {fsize/1024/1024/1024:.2f} GB")
    
    # Full scan for missing week dates
    found = {}
    found_contexts = {}  # Store context around finds
    
    scan_limit = fsize  # Scan EVERYTHING
    chunk_size = 50 * 1024 * 1024
    offset = 0
    
    try:
        with open(JOURNAL, 'rb') as f:
            while offset < scan_limit:
                try:
                    f.seek(offset)
                    chunk = f.read(chunk_size + 1024)  # overlap
                    if not chunk:
                        break
                    
                    for d in ALL_SEARCH:
                        db = d.encode('utf-8')
                        pos = 0
                        while True:
                            idx = chunk.find(db, pos)
                            if idx == -1:
                                break
                            pos = idx + 1
                            
                            found[d] = found.get(d, 0) + 1
                            
                            # Save first few contexts
                            if d not in found_contexts:
                                found_contexts[d] = []
                            if len(found_contexts[d]) < 3:
                                start = max(0, idx - 200)
                                end = min(len(chunk), idx + 300)
                                ctx = chunk[start:end].decode('utf-8', errors='replace').replace('\x00', '')
                                found_contexts[d].append({
                                    'offset': offset + idx,
                                    'context': ctx
                                })
                    
                    offset += chunk_size
                    if offset % (2 * 1024 * 1024 * 1024) == 0:
                        print(f"    ...scanned {offset/1024/1024/1024:.0f} GB of {fsize/1024/1024/1024:.0f} GB")
                except:
                    offset += chunk_size
                    continue
    except Exception as e:
        print(f"  Scan error: {e}")
    
    print(f"\n  Journal scan results:")
    if found:
        for d in sorted(found.keys()):
            flag = " *** MISSING WEEK!" if d in MISSING_DATES or d in MISSING_DATES_ALT else ""
            print(f"    {d}: {found[d]} occurrences{flag}")
            if d in found_contexts:
                for ctx in found_contexts[d][:2]:
                    print(f"      Offset {ctx['offset']}: ...{ctx['context'][:200]}...")
    else:
        print(f"    NO missing-week dates found in journal")

else:
    print(f"\n  Journal file not found")


print(f"\n\n{'='*100}")
print("SEARCH COMPLETE")
print(f"{'='*100}")
