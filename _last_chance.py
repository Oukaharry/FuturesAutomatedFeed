#!/usr/bin/env python3
"""
LAST CHANCE RECOVERY — check data_history table (correct column: created_at)
and full scan of the 19.7GB journal for March 26 - April 1 data.

Run: python3 _last_chance.py
"""
import os, sys, json, sqlite3, struct, re
from datetime import datetime

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')  # 48GB
CURRENT_DB = os.path.join(DASH_DIR, 'dashboard.db')
JOURNAL    = os.path.join(DASH_DIR, '.nfs00000000048053f600025d72')   # 19.7GB
BACKUP_DB  = os.path.join(DASH_DIR, 'dashboard.db.backup_20260311_103843')

MISSING = ['2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
           '2026-03-30', '2026-03-31', '2026-04-01']

print("=" * 100)
print("LAST CHANCE DATA RECOVERY — searching for March 26 - April 1 data")
print(f"Time: {datetime.now()}")
print("=" * 100)


# ═══════════════════════════════════════════════════════════════
# CHECK 1: data_history in 48GB DB (using correct column: created_at)
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("CHECK 1: data_history TABLE IN 48GB DB (column: created_at)")
print(f"{'='*100}")

try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    # Schema
    cols = [r[1] for r in conn.execute("PRAGMA table_info(data_history)").fetchall()]
    total = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
    print(f"  Columns: {cols}")
    print(f"  Total rows: {total}")
    
    # Check created_at distribution
    print(f"\n  created_at distribution (recent):")
    dist = conn.execute("""
        SELECT SUBSTR(created_at, 1, 10) as day, COUNT(*) as cnt 
        FROM data_history 
        WHERE created_at >= '2026-03-20'
        GROUP BY day ORDER BY day DESC
    """).fetchall()
    
    for r in dist:
        flag = " *** MISSING WEEK DATA!" if r['day'] in MISSING else ""
        print(f"    {r['day']}: {r['cnt']} snapshots{flag}")
    
    # Check for missing week entries
    for d in MISSING:
        rows = conn.execute("""
            SELECT client_id, created_at, action, change_source, change_description,
                   LENGTH(evaluations) as eval_len, LENGTH(statistics) as stats_len
            FROM data_history 
            WHERE created_at LIKE ?
            ORDER BY created_at
        """, (f"{d}%",)).fetchall()
        
        if rows:
            print(f"\n  *** {d}: {len(rows)} SNAPSHOTS FOUND! ***")
            for r in rows:
                print(f"    {r['created_at']} | {r['client_id']:<25} | {r['action']} | {r['change_source']} | evals={r['eval_len']} bytes | stats={r['stats_len']} bytes")
                print(f"      desc: {r['change_description']}")
    
    # Also show the latest entries
    print(f"\n  Latest 20 data_history entries:")
    latest = conn.execute("""
        SELECT client_id, created_at, action, change_source, change_description
        FROM data_history ORDER BY created_at DESC LIMIT 20
    """).fetchall()
    for r in latest:
        flag = " ***" if any(d in str(r['created_at']) for d in MISSING) else ""
        print(f"    {r['created_at']} | {r['client_id']:<25} | {r['action']} | {r['change_source']}{flag}")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
# CHECK 2: data_history in CURRENT DB
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("CHECK 2: data_history TABLE IN CURRENT DB")
print(f"{'='*100}")

try:
    conn = sqlite3.connect(CURRENT_DB)
    conn.row_factory = sqlite3.Row
    
    total = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
    print(f"  Total rows: {total}")
    
    print(f"\n  created_at distribution (recent):")
    dist = conn.execute("""
        SELECT SUBSTR(created_at, 1, 10) as day, COUNT(*) as cnt 
        FROM data_history 
        WHERE created_at >= '2026-03-20'
        GROUP BY day ORDER BY day DESC
    """).fetchall()
    
    for r in dist:
        flag = " *** MISSING WEEK DATA!" if r['day'] in MISSING else ""
        print(f"    {r['day']}: {r['cnt']} snapshots{flag}")
    
    for d in MISSING:
        rows = conn.execute("""
            SELECT client_id, created_at, action, change_source,
                   LENGTH(evaluations) as eval_len
            FROM data_history WHERE created_at LIKE ?
        """, (f"{d}%",)).fetchall()
        if rows:
            print(f"\n  *** {d}: {len(rows)} SNAPSHOTS! ***")
            for r in rows:
                print(f"    {r['created_at']} | {r['client_id']:<25} | {r['action']} | evals={r['eval_len']} bytes")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════════
# CHECK 3: data_history in March 11 backup
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("CHECK 3: data_history TABLE IN MARCH 11 BACKUP")
print(f"{'='*100}")

try:
    conn = sqlite3.connect(f'file:{BACKUP_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
    print(f"  Total rows: {total}")
    
    if total > 0:
        latest = conn.execute("SELECT created_at FROM data_history ORDER BY created_at DESC LIMIT 5").fetchall()
        print(f"  Latest entries: {[r['created_at'] for r in latest]}")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════════
# CHECK 4: audit_log for the missing week (what pushes happened?)
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("CHECK 4: AUDIT LOG — what happened March 25 - April 2?")
print(f"{'='*100}")

for label, path in [('48GB deleted', CORRUPT_DB), ('current', CURRENT_DB)]:
    print(f"\n  --- {label} ---")
    try:
        if '48GB' in label:
            conn = sqlite3.connect(f'file:{path}?immutable=1', uri=True)
        else:
            conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        
        cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        print(f"  Columns: {cols}")
        
        # Daily summary from March 25 to April 2
        time_col = 'timestamp' if 'timestamp' in cols else 'created_at'
        
        daily = conn.execute(f"""
            SELECT SUBSTR({time_col}, 1, 10) as day, COUNT(*) as cnt
            FROM audit_log
            WHERE {time_col} >= '2026-03-25' AND {time_col} <= '2026-04-03'
            GROUP BY day ORDER BY day
        """).fetchall()
        
        print(f"\n  Daily audit activity (Mar 25 - Apr 2):")
        for r in daily:
            flag = " <-- MISSING WEEK" if r['day'] in MISSING else ""
            print(f"    {r['day']}: {r['cnt']:>6} entries{flag}")
        
        # For each missing day, show action breakdown
        action_col = 'action' if 'action' in cols else 'event'
        for d in MISSING:
            try:
                actions = conn.execute(f"""
                    SELECT {action_col}, COUNT(*) as cnt
                    FROM audit_log WHERE {time_col} LIKE ?
                    GROUP BY {action_col} ORDER BY cnt DESC
                """, (f"{d}%",)).fetchall()
                if actions:
                    print(f"\n    {d} actions:")
                    for a in actions:
                        print(f"      {a[0]}: {a[1]}")
            except:
                pass
        
        conn.close()
    except Exception as e:
        print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════════
# CHECK 5: FULL scan of 19.7GB journal for missing week
# ═══════════════════════════════════════════════════════════════
if os.path.exists(JOURNAL):
    print(f"\n\n{'='*100}")
    print("CHECK 5: FULL SCAN OF 19.7GB JOURNAL FOR MISSING WEEK")
    print(f"{'='*100}")
    
    fsize = os.path.getsize(JOURNAL)
    print(f"  File size: {fsize/1024/1024/1024:.2f} GB")
    print(f"  Scanning ENTIRE file for March 26 - April 1 dates...")
    
    ALL_SEARCH = MISSING + ['03/26/2026', '03/27/2026', '03/28/2026', '03/29/2026',
                             '03/30/2026', '03/31/2026', '04/01/2026',
                             '3/26/2026', '3/27/2026', '3/28/2026', '3/29/2026',
                             '3/30/2026', '3/31/2026', '4/1/2026']
    
    found = {}
    found_contexts = {}
    chunk_size = 50 * 1024 * 1024  # 50MB
    offset = 0
    
    try:
        with open(JOURNAL, 'rb') as f:
            while offset < fsize:
                try:
                    f.seek(offset)
                    chunk = f.read(chunk_size + 2048)
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
                            
                            if d not in found_contexts:
                                found_contexts[d] = []
                            if len(found_contexts[d]) < 5:
                                start = max(0, idx - 300)
                                end = min(len(chunk), idx + 500)
                                ctx = chunk[start:end].decode('utf-8', errors='replace').replace('\x00', '')
                                found_contexts[d].append({
                                    'abs_offset': offset + idx,
                                    'context': ctx
                                })
                    
                    offset += chunk_size
                    gb_done = offset / 1024 / 1024 / 1024
                    if int(gb_done) != int((offset - chunk_size) / 1024 / 1024 / 1024):
                        total_found = sum(found.values())
                        print(f"    ...{gb_done:.0f}/{fsize/1024/1024/1024:.0f} GB — {total_found} matches so far")
                except Exception as e:
                    offset += chunk_size
                    continue
    except Exception as e:
        print(f"  Scan error: {e}")
    
    if found:
        print(f"\n  JOURNAL SCAN RESULTS:")
        for d in sorted(found.keys()):
            print(f"    {d}: {found[d]} occurrences")
            if d in found_contexts:
                for i, ctx in enumerate(found_contexts[d][:3]):
                    print(f"      [{i+1}] offset {ctx['abs_offset']}:")
                    # Try to find client-related info
                    text = ctx['context']
                    # Look for client names nearby
                    names = re.findall(r'[A-Z][a-z]+ [A-Z][a-z]+', text[:300])
                    if names:
                        print(f"          names nearby: {names[:5]}")
                    # Show snippet around the date
                    date_pos = text.find(d)
                    if date_pos >= 0:
                        snippet = text[max(0,date_pos-100):date_pos+200]
                        print(f"          ...{snippet[:300]}...")
    else:
        print(f"\n  NO missing week dates found in journal (scanned {fsize/1024/1024/1024:.1f} GB)")

else:
    print(f"\n  Journal file not found")


# ═══════════════════════════════════════════════════════════════
# CHECK 6: Check if WAL ghost file has any data
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("CHECK 6: ALL NFS GHOST FILES — looking for any with data")
print(f"{'='*100}")

for root, dirs, files in os.walk(os.path.expanduser('~/MT5Dashboard')):
    for f in files:
        if f.startswith('.nfs'):
            path = os.path.join(root, f)
            size = os.path.getsize(path)
            if size > 0:
                try:
                    with open(path, 'rb') as fh:
                        header = fh.read(32)
                    header_hex = header[:16].hex()
                    
                    file_type = "unknown"
                    if header[:16] == b'SQLite format 3\x00':
                        file_type = "SQLite DB"
                    elif header[:8] == b'\xd9\xd5\x05\xf9\x20\xa1\x63\xd7':
                        file_type = "ROLLBACK JOURNAL"
                    elif header[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
                        file_type = "WAL FILE !!!"
                    
                    rel = path.replace(os.path.expanduser('~') + '/', '~/')
                    sz = f"{size/1024/1024:.1f} MB" if size < 1024*1024*1024 else f"{size/1024/1024/1024:.2f} GB"
                    print(f"  {sz:>12}  {file_type:<20}  {rel}  header={header_hex}")
                except Exception as e:
                    print(f"  Error reading {f}: {e}")


print(f"\n\n{'='*100}")
print("RECOVERY SEARCH COMPLETE")
print(f"{'='*100}")
