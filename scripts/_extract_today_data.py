#!/usr/bin/env python3
"""
Extract today's fresh data from the old corrupt 48GB DB.
Tries to read each client's data individually (some pages may be readable even if DB is corrupt overall).
Targets data from around 9 AM Kenyan time (06:00 UTC) on April 2, 2026.

Run on PythonAnywhere: python3 _extract_today_data.py
"""
import sqlite3, json, os, sys
from datetime import datetime, date

DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB = os.path.join(DASH_DIR, 'dashboard.db')

# Find the big corrupt DB
corrupt_files = []
for f in os.listdir(DASH_DIR):
    fp = os.path.join(DASH_DIR, f)
    if os.path.isfile(fp) and f != 'dashboard.db':
        sz = os.path.getsize(fp)
        if sz > 1_000_000_000:  # > 1GB
            corrupt_files.append((fp, f, sz))

# Also check backup
backup = os.path.join(DASH_DIR, 'dashboard.db.backup_20260311_103843')
if os.path.exists(backup):
    corrupt_files.append((backup, os.path.basename(backup), os.path.getsize(backup)))

corrupt_files.sort(key=lambda x: -x[2])  # Largest first

print("=" * 90)
print("SEARCHING FOR TODAY'S DATA IN OLD/CORRUPT DBs")
print(f"Target: April 2, 2026 data (around 09:00 Kenyan / 06:00 UTC)")
print("=" * 90)

for fp, fn, sz in corrupt_files:
    print(f"\n{'='*90}")
    print(f"FILE: {fn}  ({sz/1024/1024/1024:.1f} GB)")
    print(f"{'='*90}")
    
    try:
        conn = sqlite3.connect(f'file:{fp}?mode=ro', uri=True, timeout=10)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA cache_size=10000")
    except Exception as e:
        print(f"  Cannot open: {e}")
        continue
    
    # 1. Check audit_log for today's entries
    print("\n--- AUDIT LOG: Today's entries ---")
    try:
        rows = conn.execute("""
            SELECT timestamp, action, details FROM audit_log 
            WHERE timestamp LIKE '2026-04-02%'
            ORDER BY timestamp DESC
        """).fetchall()
        print(f"  Found {len(rows)} entries from today")
        for r in rows[:20]:
            print(f"    {r[0]} | {r[1]} | {str(r[2])[:80]}")
        if len(rows) > 20:
            print(f"    ... and {len(rows)-20} more")
    except Exception as e:
        print(f"  Error reading audit_log: {e}")
    
    # 2. Check audit_log for CLIENT_DATA_PUSH entries (these are the trader companion pushes)
    print("\n--- CLIENT DATA PUSHES (most recent) ---")
    try:
        rows = conn.execute("""
            SELECT timestamp, action, details FROM audit_log 
            WHERE action = 'CLIENT_DATA_PUSH'
            ORDER BY timestamp DESC LIMIT 20
        """).fetchall()
        for r in rows:
            print(f"    {r[0]} | {str(r[2])[:100]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 3. Try to get data_history entries from today
    print("\n--- DATA HISTORY (today's snapshots) ---")
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if 'data_history' in tables:
            # Check schema
            schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='data_history'").fetchone()
            print(f"  Schema: {schema[0][:200] if schema else 'unknown'}")
            
            try:
                rows = conn.execute("""
                    SELECT * FROM data_history 
                    WHERE timestamp LIKE '2026-04-02%' OR saved_at LIKE '2026-04-02%'
                    ORDER BY rowid DESC LIMIT 10
                """).fetchall()
                print(f"  Found {len(rows)} entries from today")
                if rows:
                    cols = [d[0] for d in conn.execute("SELECT * FROM data_history LIMIT 0").description]
                    print(f"  Columns: {cols}")
                    for r in rows:
                        print(f"    {r[:3]}...")  # Just first 3 columns
            except Exception as e1:
                # Try without the column name guess
                try:
                    cnt = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
                    print(f"  Total rows: {cnt}")
                    cols = [d[0] for d in conn.execute("SELECT * FROM data_history LIMIT 0").description]
                    print(f"  Columns: {cols}")
                    # Get most recent entries
                    rows = conn.execute(f"SELECT * FROM data_history ORDER BY rowid DESC LIMIT 5").fetchall()
                    for r in rows:
                        # Print first few fields
                        print(f"    {str(r)[:200]}")
                except Exception as e2:
                    print(f"  Error reading data_history: {e2}")
        else:
            print("  data_history table not found")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 4. Try to read each client's data individually and check freshness
    print("\n--- CLIENT DATA FRESHNESS (per-client extraction) ---")
    try:
        # Get list of client IDs
        client_ids = []
        try:
            client_ids = [r[0] for r in conn.execute("SELECT client_id FROM clients_data").fetchall()]
        except:
            # If that fails, try one at a time
            for rid in range(1, 200):
                try:
                    row = conn.execute("SELECT client_id FROM clients_data WHERE rowid=?", (rid,)).fetchone()
                    if row:
                        client_ids.append(row[0])
                except:
                    break
        
        print(f"  Found {len(client_ids)} clients")
        
        fresher_clients = []
        
        for cid in client_ids:
            try:
                row = conn.execute(
                    "SELECT client_id, evaluations, statistics, account FROM clients_data WHERE client_id=?", 
                    (cid,)
                ).fetchone()
                if not row:
                    continue
                
                # Check evaluations for today's dates or newer dates
                dates_found = set()
                day_refs = set()
                eval_count = 0
                
                try:
                    evals = json.loads(row[1]) if row[1] else []
                    eval_count = len(evals)
                    for ev in evals:
                        if not isinstance(ev, dict):
                            continue
                        for k, v in ev.items():
                            if isinstance(v, str):
                                # Check for today's date in any format
                                if '2026-04-02' in v or '04/02/26' in v or '4/2/26' in v or '04/02/2026' in v:
                                    dates_found.add(f"{k}={v}")
                                # Check for recent dates (last 7 days)
                                for month_day in ['03/31', '04/01', '04/02', '03-31', '04-01', '04-02']:
                                    if month_day in v:
                                        dates_found.add(f"{k}={v}")
                                # Check day of week references
                                for day in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY']:
                                    if day in v.upper():
                                        day_refs.add(v.strip()[:30])
                except:
                    pass
                
                # Check statistics for timestamps
                stats_dates = set()
                try:
                    stats = json.loads(row[2]) if row[2] else {}
                    def find_dates(d, prefix=''):
                        if isinstance(d, dict):
                            for k, v in d.items():
                                if isinstance(v, str) and ('2026-04' in v or '04/0' in v):
                                    stats_dates.add(f"{prefix}{k}={v}")
                                elif isinstance(v, dict):
                                    find_dates(v, prefix+k+'.')
                    find_dates(stats)
                except:
                    pass
                
                # Check account blob
                acct_info = {}
                try:
                    acct = json.loads(row[3]) if row[3] else {}
                    if isinstance(acct, dict):
                        for k in ['last_push', 'last_update', 'last_modified', 'pushed_at', 'updated_at']:
                            if k in acct:
                                acct_info[k] = acct[k]
                except:
                    pass
                
                # Compare with current DB
                is_fresher = False
                cur_eval_count = 0
                try:
                    cur_conn = sqlite3.connect(f'file:{CUR_DB}?mode=ro', uri=True)
                    cur_row = cur_conn.execute("SELECT evaluations FROM clients_data WHERE client_id=?", (cid,)).fetchone()
                    if cur_row:
                        cur_evals = json.loads(cur_row[0]) if cur_row[0] else []
                        cur_eval_count = len(cur_evals)
                        if eval_count > cur_eval_count:
                            is_fresher = True
                    cur_conn.close()
                except:
                    pass
                
                if dates_found or day_refs or is_fresher or acct_info:
                    fresher_clients.append({
                        'cid': cid,
                        'eval_count': eval_count,
                        'cur_eval_count': cur_eval_count,
                        'is_fresher': is_fresher,
                        'dates': dates_found,
                        'days': day_refs,
                        'stats_dates': stats_dates,
                        'acct_info': acct_info
                    })
                    
            except Exception as e:
                print(f"    {cid}: Error - {e}")
        
        if fresher_clients:
            print(f"\n  *** CLIENTS WITH POTENTIALLY NEWER DATA: {len(fresher_clients)} ***")
            for c in fresher_clients:
                marker = " <<<< FRESHER!" if c['is_fresher'] else ""
                print(f"\n  {c['cid']}: old={c['eval_count']} evals, current={c['cur_eval_count']} evals{marker}")
                if c['dates']:
                    print(f"    Recent dates in evals: {c['dates']}")
                if c['days']:
                    print(f"    Day references: {c['days']}")
                if c['stats_dates']:
                    print(f"    Stats dates: {c['stats_dates']}")
                if c['acct_info']:
                    print(f"    Account info: {c['acct_info']}")
        else:
            print(f"\n  No clients found with data newer than current DB")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 5. Check kyc_links
    print("\n--- KYC LINKS ---")
    try:
        rows = conn.execute("SELECT * FROM kyc_links").fetchall()
        print(f"  {len(rows)} links found")
    except Exception as e:
        print(f"  Error: {e}")
    
    conn.close()

# Also compare current DB audit log for timeline
print(f"\n{'='*90}")
print("CURRENT DB: Last pushes timeline")
print(f"{'='*90}")
try:
    conn = sqlite3.connect(f'file:{CUR_DB}?mode=ro', uri=True)
    rows = conn.execute("""
        SELECT timestamp, action, details FROM audit_log
        WHERE action = 'CLIENT_DATA_PUSH'
        ORDER BY timestamp DESC LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  {r[0]} | {str(r[2])[:100]}")
    
    print(f"\n  All pushes today:")
    rows = conn.execute("""
        SELECT timestamp, action, details FROM audit_log
        WHERE action = 'CLIENT_DATA_PUSH' AND timestamp LIKE '2026-04-02%'
        ORDER BY timestamp
    """).fetchall()
    for r in rows:
        print(f"  {r[0]} | {str(r[2])[:100]}")
    conn.close()
except Exception as e:
    print(f"  Error: {e}")

print(f"\n{'='*90}")
print("DONE")
print(f"{'='*90}")
