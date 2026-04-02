#!/usr/bin/env python3
"""
Try every trick to get data_history rows from the 48GB corrupt DB.
The table exists but COUNT(*) fails — try row-by-row with error recovery.

Run: python3 _recover_history.py
"""
import os, sys, json, sqlite3, struct
from datetime import datetime

CORRUPT_DB = os.path.expanduser('~/MT5Dashboard/dashboard/.nfs0000000004802cdb0000de98')
CURRENT_DB = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')

print("=" * 100)
print("DATA_HISTORY RECOVERY FROM 48GB DB")
print(f"Time: {datetime.now()}")
print("=" * 100)


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 1: Read with LIMIT/OFFSET — skip past corrupt pages
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 1: LIMIT/OFFSET iteration ---")
try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    cols = [r[1] for r in conn.execute("PRAGMA table_info(data_history)").fetchall()]
    print(f"  Schema OK: {cols}")
    
    recovered = []
    errors = 0
    
    for offset in range(0, 100000, 1):
        try:
            row = conn.execute(f"SELECT * FROM data_history LIMIT 1 OFFSET {offset}").fetchone()
            if row is None:
                break
            recovered.append(dict(row))
            if len(recovered) % 100 == 0:
                print(f"    ...recovered {len(recovered)} rows (offset {offset})")
        except sqlite3.DatabaseError as e:
            errors += 1
            if errors <= 5:
                print(f"    Error at offset {offset}: {e}")
            if errors > 50:
                print(f"    Too many errors ({errors}), stopping LIMIT/OFFSET")
                break
            continue
    
    print(f"  Result: {len(recovered)} rows recovered, {errors} errors")
    if recovered:
        dates = set()
        for r in recovered:
            ca = r.get('created_at', '')
            if ca:
                dates.add(ca[:10])
        print(f"  Dates found: {sorted(dates)}")
    
    conn.close()
except Exception as e:
    print(f"  Failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 2: Read by known client_ids
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 2: Query by client_id ---")
try:
    # Get client list from current DB
    cur = sqlite3.connect(CURRENT_DB)
    clients = [r[0] for r in cur.execute("SELECT client_id FROM clients_data").fetchall()]
    cur.close()
    print(f"  Got {len(clients)} client IDs from current DB")
    
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    recovered2 = []
    for cid in clients:
        try:
            rows = conn.execute(
                "SELECT client_id, created_at, action, change_source, change_description "
                "FROM data_history WHERE client_id = ? ORDER BY created_at",
                (cid,)
            ).fetchall()
            for r in rows:
                recovered2.append(dict(r))
        except sqlite3.DatabaseError:
            continue
    
    print(f"  Result: {len(recovered2)} rows recovered across {len(clients)} clients")
    if recovered2:
        dates = set()
        for r in recovered2:
            ca = r.get('created_at', '')
            if ca:
                dates.add(ca[:10])
        print(f"  Dates found: {sorted(dates)}")
        
        # Show entries for missing week
        missing_week = [r for r in recovered2 if r.get('created_at', '')[:10] in 
                       ['2026-03-26','2026-03-27','2026-03-28','2026-03-29','2026-03-30','2026-03-31','2026-04-01']]
        if missing_week:
            print(f"\n  *** MISSING WEEK ENTRIES: {len(missing_week)} ***")
            for r in missing_week:
                print(f"    {r['created_at']} | {r['client_id']} | {r['action']} | {r['change_source']}")
    
    conn.close()
except Exception as e:
    print(f"  Failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 3: Read by rowid range
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 3: Query by rowid ---")
try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    # Find max rowid
    try:
        maxid = conn.execute("SELECT MAX(rowid) FROM data_history").fetchone()[0]
        print(f"  MAX(rowid) = {maxid}")
    except:
        maxid = 10000
        print(f"  Can't get MAX(rowid), trying up to {maxid}")
    
    recovered3 = []
    errors3 = 0
    
    for rid in range(1, min(maxid + 1, 100001) if maxid else 100001):
        try:
            row = conn.execute("SELECT * FROM data_history WHERE rowid = ?", (rid,)).fetchone()
            if row:
                recovered3.append(dict(row))
                if len(recovered3) % 100 == 0:
                    print(f"    ...recovered {len(recovered3)} at rowid {rid}")
        except sqlite3.DatabaseError:
            errors3 += 1
            continue
    
    print(f"  Result: {len(recovered3)} rows recovered, {errors3} errors")
    if recovered3:
        dates = set()
        for r in recovered3:
            ca = r.get('created_at', '')
            if ca:
                dates.add(ca[:10])
        print(f"  Dates found: {sorted(dates)}")
        
        missing_week = [r for r in recovered3 if r.get('created_at', '')[:10] in 
                       ['2026-03-26','2026-03-27','2026-03-28','2026-03-29','2026-03-30','2026-03-31','2026-04-01']]
        if missing_week:
            print(f"\n  *** MISSING WEEK ENTRIES: {len(missing_week)} ***")
            for r in missing_week[:20]:
                print(f"    {r['created_at']} | {r['client_id']} | {r['action']}")
    
    conn.close()
except Exception as e:
    print(f"  Failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 4: Try .recover command approach — dump readable pages
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 4: PRAGMA integrity_check on data_history ---")
try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    
    # Check which tables are accessible
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"  Tables found: {[t[0] for t in tables]}")
    
    for tbl in [t[0] for t in tables]:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
            print(f"    {tbl}: {cnt} rows ✓")
        except sqlite3.DatabaseError as e:
            print(f"    {tbl}: CORRUPT ({e})")
    
    conn.close()
except Exception as e:
    print(f"  Failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 5: Check clients_data for last_updated AFTER March 25
# (The clients_data WAS readable before — check if any rows have
#  last_updated dates in the missing week)
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 5: clients_data last_updated in 48GB DB ---")
try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("""
        SELECT client_id, last_updated 
        FROM clients_data 
        WHERE last_updated > '2026-03-25'
        ORDER BY last_updated DESC
    """).fetchall()
    
    if rows:
        print(f"  {len(rows)} clients with last_updated AFTER March 25:")
        for r in rows:
            print(f"    {r['last_updated']} | {r['client_id']}")
    else:
        print(f"  NO clients have last_updated after March 25")
    
    # Also show distribution
    dist = conn.execute("""
        SELECT SUBSTR(last_updated, 1, 10) as day, COUNT(*) 
        FROM clients_data GROUP BY day ORDER BY day DESC
    """).fetchall()
    print(f"\n  last_updated distribution:")
    for r in dist:
        print(f"    {r[0]}: {r[1]} clients")
    
    conn.close()
except Exception as e:
    print(f"  Failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ATTEMPT 6: Raw binary search of 48GB DB for data_history rows
# Just search for the created_at pattern with missing week dates
# ═══════════════════════════════════════════════════════════════
print(f"\n--- ATTEMPT 6: Raw binary scan of 48GB for data_history timestamps ---")
MISSING = ['2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
           '2026-03-30', '2026-03-31', '2026-04-01']

fsize = os.path.getsize(CORRUPT_DB)
print(f"  File size: {fsize/1024/1024/1024:.2f} GB")
print(f"  Searching for missing week dates...")

found = {}
found_contexts = {}
chunk_size = 100 * 1024 * 1024  # 100MB
offset = 0

try:
    with open(CORRUPT_DB, 'rb') as f:
        while offset < fsize:
            f.seek(offset)
            chunk = f.read(chunk_size + 4096)
            if not chunk:
                break
            
            for d in MISSING:
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
                    if len(found_contexts[d]) < 3:
                        start = max(0, idx - 200)
                        end = min(len(chunk), idx + 400)
                        ctx = chunk[start:end].decode('utf-8', errors='replace').replace('\x00', '')
                        found_contexts[d].append({
                            'abs_offset': offset + idx,
                            'context': ctx[:500]
                        })
            
            offset += chunk_size
            gb = offset / 1024/1024/1024
            if int(gb) != int((offset - chunk_size)/1024/1024/1024):
                print(f"    ...{gb:.0f}/{fsize/1024/1024/1024:.0f} GB — {sum(found.values())} matches")

except Exception as e:
    print(f"  Error: {e}")

if found:
    print(f"\n  48GB DB RAW SCAN RESULTS:")
    for d in sorted(found.keys()):
        print(f"    {d}: {found[d]} occurrences")
        if d in found_contexts:
            for i, ctx in enumerate(found_contexts[d]):
                # Check if this looks like a data_history created_at or just a field value
                text = ctx['context']
                is_history = 'created_at' in text or 'change_source' in text or 'action' in text
                is_field = 'Date Started' in text or 'Date Purchased' in text or 'Date Ended' in text or '"time"' in text
                label = "DATA_HISTORY?" if is_history else ("FIELD VALUE" if is_field else "UNKNOWN")
                print(f"      [{i+1}] offset {ctx['abs_offset']} — {label}")
                print(f"          {text[:300]}")
else:
    print(f"  NO missing week dates found in 48GB DB")


print(f"\n\n{'='*100}")
print("RECOVERY COMPLETE")
print(f"{'='*100}")
