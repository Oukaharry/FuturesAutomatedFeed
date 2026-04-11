#!/usr/bin/env python3
"""
Find which DB has data between March 25 - April 1, 2026.
Checks ALL available databases and the rollback journal.

Run: python3 _find_fresh_data.py
"""
import os, sys, json, sqlite3, re, struct
from datetime import datetime

DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')
HOME     = os.path.expanduser('~')

# All known DBs
DBS = {
    'current':  os.path.join(DASH_DIR, 'dashboard.db'),
    '48GB_nfs': os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98'),
    '19GB_nfs': os.path.join(DASH_DIR, '.nfs00000000048053f600025d72'),
    'backup_0311': os.path.join(DASH_DIR, 'dashboard.db.backup_20260311_103843'),
}

# Also find any other .db files
for root, dirs, files in os.walk(HOME):
    # Skip deep directories
    if root.count(os.sep) - HOME.count(os.sep) > 3:
        continue
    for f in files:
        if f.endswith('.db') or f.endswith('.sqlite') or f.endswith('.sqlite3'):
            path = os.path.join(root, f)
            key = f"found_{f}_{os.path.basename(root)}"
            if path not in DBS.values():
                DBS[key] = path

TARGET_DATES = [
    '2026-03-25', '2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29',
    '2026-03-30', '2026-03-31', '2026-04-01', '2026-04-02',
]
TARGET_DATES_ALT = [
    '03/25/2026', '03/26/2026', '03/27/2026', '03/28/2026', '03/29/2026',
    '03/30/2026', '03/31/2026', '04/01/2026', '04/02/2026',
    '3/25/2026', '3/26/2026', '3/27/2026', '3/28/2026', '3/29/2026',
    '3/30/2026', '3/31/2026', '4/1/2026', '4/2/2026',
    '03/25/26', '03/26/26', '03/27/26', '03/28/26', '03/29/26',
    '03/30/26', '03/31/26', '04/01/26', '04/02/26',
]

# Day names that correspond to Mar 25 - Apr 1
# Mar 25 = Wed, Mar 26 = Thu, Mar 27 = Fri, Mar 28 = Sat, Mar 29 = Sun
# Mar 30 = Mon, Mar 31 = Tue, Apr 1 = Wed, Apr 2 = Thu
RECENT_DAYS = ['WEDNESDAY', 'THURSDAY', 'FRIDAY']  # Trading days

def safe_json(blob):
    if not blob:
        return None
    try:
        return json.loads(blob) if isinstance(blob, str) else json.loads(blob.decode('utf-8', 'replace'))
    except:
        return None

def search_evals_for_dates(evals_json, target_dates):
    """Search evaluations for any of the target dates. Returns dict of date -> count."""
    evals = safe_json(evals_json)
    if not isinstance(evals, list):
        return {}
    
    found = {}
    for ev in evals:
        if not isinstance(ev, dict):
            continue
        ev_str = json.dumps(ev)
        for d in target_dates:
            if d in ev_str:
                found[d] = found.get(d, 0) + 1
    return found

def try_connect(path, label):
    """Try multiple connection methods."""
    methods = [
        ('immutable', lambda: sqlite3.connect(f'file:{path}?immutable=1', uri=True)),
        ('readonly',  lambda: sqlite3.connect(f'file:{path}?mode=ro', uri=True)),
        ('normal',    lambda: sqlite3.connect(path, timeout=30)),
    ]
    for name, fn in methods:
        try:
            conn = fn()
            conn.row_factory = sqlite3.Row
            # Quick test
            conn.execute("SELECT 1")
            return conn, name
        except Exception as e:
            continue
    return None, None


print("=" * 100)
print(f"SEARCHING ALL DATABASES FOR DATA BETWEEN MARCH 25 - APRIL 2, 2026")
print(f"Time: {datetime.now()}")
print("=" * 100)

for label, path in sorted(DBS.items()):
    if not os.path.exists(path):
        continue
    
    size_gb = os.path.getsize(path) / 1024 / 1024 / 1024
    print(f"\n{'='*100}")
    print(f"DB: {label}")
    print(f"Path: {path}")
    print(f"Size: {size_gb:.2f} GB")
    print(f"{'='*100}")
    
    conn, method = try_connect(path, label)
    if not conn:
        print(f"  *** CANNOT OPEN — trying raw scan ***")
        
        # Raw byte scan for dates
        print(f"  Scanning raw bytes for target dates...")
        raw_found = {}
        try:
            with open(path, 'rb') as f:
                chunk_size = 50 * 1024 * 1024  # 50MB
                offset = 0
                fsize = os.path.getsize(path)
                scan_limit = min(fsize, 10 * 1024 * 1024 * 1024)  # 10GB
                
                while offset < scan_limit:
                    try:
                        f.seek(offset)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        
                        for d in TARGET_DATES + TARGET_DATES_ALT:
                            db = d.encode('utf-8')
                            count = chunk.count(db)
                            if count > 0:
                                raw_found[d] = raw_found.get(d, 0) + count
                        
                        offset += chunk_size
                        if offset % (500 * 1024 * 1024) == 0:
                            print(f"    ...scanned {offset/1024/1024/1024:.1f} GB")
                    except:
                        offset += chunk_size
                        continue
        except Exception as e:
            print(f"    Raw scan error: {e}")
        
        if raw_found:
            print(f"  RAW SCAN RESULTS:")
            for d in sorted(raw_found.keys()):
                print(f"    {d}: {raw_found[d]} occurrences")
        else:
            print(f"  No target dates found in raw scan")
        continue
    
    print(f"  Connected via: {method}")
    
    # Get tables
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"  Tables: {tables}")
    except Exception as e:
        print(f"  Cannot list tables: {e}")
        conn.close()
        continue
    
    # Check clients_data evaluations
    if 'clients_data' in tables:
        print(f"\n  --- clients_data ---")
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(clients_data)").fetchall()]
            count = conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
            print(f"  Columns: {cols}")
            print(f"  Total clients: {count}")
            
            total_date_hits = {}
            clients_with_fresh = []
            
            rows = conn.execute("SELECT client_id, evaluations FROM clients_data").fetchall()
            for row in rows:
                cid = row['client_id']
                hits = search_evals_for_dates(row['evaluations'], TARGET_DATES + TARGET_DATES_ALT)
                if hits:
                    clients_with_fresh.append((cid, hits))
                    for d, c in hits.items():
                        total_date_hits[d] = total_date_hits.get(d, 0) + c
            
            if total_date_hits:
                print(f"\n  *** FOUND DATES BETWEEN MAR 25 - APR 2 ***")
                for d in sorted(total_date_hits.keys()):
                    print(f"    {d}: {total_date_hits[d]} occurrences across evaluations")
                
                print(f"\n  Clients with fresh data ({len(clients_with_fresh)}):")
                for cid, hits in sorted(clients_with_fresh, key=lambda x: -sum(x[1].values())):
                    dates = ', '.join(f"{d}({c})" for d, c in sorted(hits.items()))
                    print(f"    {cid:<30} — {dates}")
            else:
                print(f"  NO dates between Mar 25 - Apr 2 found in evaluations")
            
            # Also check for WEDNESDAY/THURSDAY day references in Hedge Result columns
            print(f"\n  Checking for recent day-of-week references...")
            day_clients = []
            for row in rows:
                cid = row['client_id']
                evals = safe_json(row['evaluations'])
                if not isinstance(evals, list):
                    continue
                for ev in evals:
                    if not isinstance(ev, dict):
                        continue
                    ev_str = json.dumps(ev)
                    for day in RECENT_DAYS:
                        if day in ev_str:
                            day_clients.append((cid, day))
                            break
            
            if day_clients:
                print(f"  Clients with recent day references: {len(day_clients)}")
                for cid, day in day_clients[:20]:
                    print(f"    {cid}: {day}")
                    
        except Exception as e:
            print(f"  Error reading clients_data: {e}")
            import traceback
            traceback.print_exc()
    
    # Check audit_log for dates in range
    if 'audit_log' in tables:
        print(f"\n  --- audit_log ---")
        try:
            for d in TARGET_DATES:
                c = conn.execute("SELECT COUNT(*) FROM audit_log WHERE timestamp LIKE ?", (f"{d}%",)).fetchone()[0]
                if c > 0:
                    print(f"    {d}: {c} entries")
                    # Show first few
                    samples = conn.execute(
                        "SELECT timestamp, action, client_id FROM audit_log WHERE timestamp LIKE ? ORDER BY timestamp LIMIT 5",
                        (f"{d}%",)
                    ).fetchall()
                    for s in samples:
                        print(f"      {s['timestamp']} | {s['action']} | {s['client_id'] or ''}")
        except Exception as e:
            print(f"    Error: {e}")
    
    # Check data_history
    if 'data_history' in tables:
        print(f"\n  --- data_history ---")
        try:
            for d in TARGET_DATES:
                c = conn.execute("SELECT COUNT(*) FROM data_history WHERE timestamp LIKE ?", (f"{d}%",)).fetchone()[0]
                if c > 0:
                    rows2 = conn.execute(
                        "SELECT client_id, timestamp FROM data_history WHERE timestamp LIKE ? ORDER BY timestamp LIMIT 5",
                        (f"{d}%",)
                    ).fetchall()
                    print(f"    {d}: {c} snapshots")
                    for r in rows2:
                        print(f"      {r['timestamp']} | {r['client_id']}")
        except Exception as e:
            print(f"    Error: {e}")
    
    # Check evaluations table
    if 'evaluations' in tables:
        print(f"\n  --- evaluations table ---")
        try:
            eval_cols = [r[1] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()]
            total = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            print(f"    Columns: {eval_cols}, Total: {total}")
            
            # Check for date columns
            date_cols = [c for c in eval_cols if 'date' in c.lower() or 'timestamp' in c.lower() or 'created' in c.lower() or 'updated' in c.lower()]
            for dc in date_cols:
                for d in TARGET_DATES:
                    try:
                        c = conn.execute(f"SELECT COUNT(*) FROM evaluations WHERE {dc} LIKE ?", (f"{d}%",)).fetchone()[0]
                        if c > 0:
                            print(f"    {dc} = {d}: {c} rows")
                    except:
                        pass
        except Exception as e:
            print(f"    Error: {e}")
    
    conn.close()

print(f"\n\n{'='*100}")
print("SEARCH COMPLETE")
print(f"{'='*100}")
