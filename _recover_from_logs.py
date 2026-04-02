#!/usr/bin/env python3
"""
Recover data from data_history in the 48GB corrupt DB + check server logs.
data_history stores FULL snapshots (deals, positions, evaluations, statistics, etc.)
on every client update — if we can read rows from March 26-April 1, we can restore.

Run: python3 _recover_from_logs.py
"""
import os, sys, json, sqlite3, glob
from datetime import datetime, timedelta
from collections import defaultdict

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')
CURRENT_DB = os.path.join(DASH_DIR, 'dashboard.db')

MISSING_DATES = ['2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
                 '2026-03-30', '2026-03-31', '2026-04-01']

print("=" * 100)
print("DATA RECOVERY FROM LOGS & HISTORY")
print(f"Time: {datetime.now()}")
print("=" * 100)


# ═══════════════════════════════════════════════════════════════
# PART 1: Recover data_history from 48GB corrupt DB
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("PART 1: RECOVER data_history FROM 48GB DB")
print(f"{'='*80}")

recovered_history = []

try:
    conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    
    cols = [r[1] for r in conn.execute("PRAGMA table_info(data_history)").fetchall()]
    print(f"  Schema: {cols}")
    
    # --- Method A: rowid iteration ---
    print(f"\n  Method A: rowid iteration...")
    max_rowid = None
    try:
        max_rowid = conn.execute("SELECT MAX(rowid) FROM data_history").fetchone()[0]
        print(f"    MAX(rowid) = {max_rowid}")
    except:
        # Try to estimate from sqlite_sequence
        try:
            seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='data_history'").fetchone()
            if seq:
                max_rowid = seq[0]
                print(f"    Estimated max from sqlite_sequence: {max_rowid}")
        except:
            max_rowid = 500000
            print(f"    Can't determine max, trying up to {max_rowid}")
    
    if max_rowid:
        errors_a = 0
        last_report = 0
        for rid in range(1, max_rowid + 1):
            try:
                row = conn.execute("SELECT * FROM data_history WHERE rowid = ?", (rid,)).fetchone()
                if row:
                    recovered_history.append(dict(row))
                    if len(recovered_history) % 500 == 0:
                        print(f"      ...{len(recovered_history)} rows at rowid {rid}")
            except sqlite3.DatabaseError:
                errors_a += 1
                if errors_a <= 3:
                    print(f"      Error at rowid {rid}")
                continue
            
            # Progress report every 10000
            if rid - last_report >= 10000:
                last_report = rid
                print(f"      ...scanning rowid {rid}/{max_rowid} — {len(recovered_history)} recovered, {errors_a} errors")
        
        print(f"    Method A result: {len(recovered_history)} rows, {errors_a} errors")
    
    # --- Method B: query by client_id ---
    if len(recovered_history) == 0:
        print(f"\n  Method B: query by client_id...")
        cur = sqlite3.connect(CURRENT_DB)
        clients = [r[0] for r in cur.execute("SELECT client_id FROM clients_data").fetchall()]
        cur.close()
        
        for cid in clients:
            try:
                rows = conn.execute("SELECT * FROM data_history WHERE client_id = ?", (cid,)).fetchall()
                for r in rows:
                    recovered_history.append(dict(r))
            except sqlite3.DatabaseError:
                continue
        
        print(f"    Method B result: {len(recovered_history)} rows")
    
    # --- Method C: query with date ranges ---
    if len(recovered_history) == 0:
        print(f"\n  Method C: direct date queries...")
        for d in MISSING_DATES:
            try:
                rows = conn.execute("SELECT * FROM data_history WHERE created_at LIKE ?", (f"{d}%",)).fetchall()
                for r in rows:
                    recovered_history.append(dict(r))
                if rows:
                    print(f"    {d}: {len(rows)} rows!")
            except sqlite3.DatabaseError:
                continue
        
        print(f"    Method C result: {len(recovered_history)} rows")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")
    import traceback; traceback.print_exc()

# Analyze recovered history
if recovered_history:
    print(f"\n  RECOVERED {len(recovered_history)} data_history rows!")
    
    # Date distribution
    date_dist = defaultdict(int)
    for r in recovered_history:
        ca = r.get('created_at', '')
        if ca:
            date_dist[ca[:10]] += 1
    
    print(f"\n  Date distribution:")
    for d in sorted(date_dist.keys()):
        flag = " *** MISSING WEEK!" if d in MISSING_DATES else ""
        print(f"    {d}: {date_dist[d]} snapshots{flag}")
    
    # Count missing week entries
    missing_week = [r for r in recovered_history if r.get('created_at', '')[:10] in MISSING_DATES]
    print(f"\n  Missing week (Mar 26-Apr 1) entries: {len(missing_week)}")
    
    if missing_week:
        # Group by client
        by_client = defaultdict(list)
        for r in missing_week:
            by_client[r['client_id']].append(r)
        
        print(f"  Clients with missing week data: {len(by_client)}")
        for cid in sorted(by_client.keys()):
            entries = by_client[cid]
            dates = sorted(set(e['created_at'][:10] for e in entries))
            has_data = any(e.get('evaluations') for e in entries)
            print(f"    {cid:<40} {len(entries)} snapshots on {dates} data={'YES' if has_data else 'NO'}")
else:
    print(f"\n  No data_history rows recovered from 48GB DB")
    print(f"  (The table's B-tree pages were likely in the WAL)")


# ═══════════════════════════════════════════════════════════════
# PART 2: Check PythonAnywhere server logs
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PART 2: PYTHONANYWHERE SERVER LOGS")
print(f"{'='*80}")

log_dirs = [
    os.path.expanduser('~/logs'),
    '/var/log',
    os.path.expanduser('~/MT5Dashboard/logs'),
    os.path.expanduser('~/MT5Dashboard/dashboard/logs'),
    os.path.expanduser('~'),
]

log_files_found = []
for ld in log_dirs:
    if os.path.exists(ld):
        try:
            for f in os.listdir(ld):
                full = os.path.join(ld, f)
                if os.path.isfile(full) and any(x in f.lower() for x in ['log', 'error', 'access', 'server', 'wsgi']):
                    size = os.path.getsize(full)
                    mtime = datetime.fromtimestamp(os.path.getmtime(full))
                    log_files_found.append((full, size, mtime))
                    print(f"  Found: {full} ({size/1024:.1f} KB, modified {mtime})")
        except PermissionError:
            pass

# Also check standard PythonAnywhere log locations
pa_logs = glob.glob(os.path.expanduser('~/var/log/*')) + \
          glob.glob('/var/log/pythonanywhere*') + \
          glob.glob(os.path.expanduser('~/*.log')) + \
          glob.glob(os.path.expanduser('~/MT5Dashboard/*.log'))

for lf in pa_logs:
    if os.path.isfile(lf):
        size = os.path.getsize(lf)
        mtime = datetime.fromtimestamp(os.path.getmtime(lf))
        if (lf, size, mtime) not in log_files_found:
            log_files_found.append((lf, size, mtime))
            print(f"  Found: {lf} ({size/1024:.1f} KB, modified {mtime})")

# Check PythonAnywhere standard paths
pa_user = os.path.basename(os.path.expanduser('~'))
for pattern in [
    f'/var/log/{pa_user}*',
    f'/var/www/{pa_user}*',
]:
    for lf in glob.glob(pattern):
        if os.path.isfile(lf):
            size = os.path.getsize(lf)
            print(f"  Found: {lf} ({size/1024:.1f} KB)")
            log_files_found.append((lf, size, None))


# ═══════════════════════════════════════════════════════════════
# PART 3: Search logs for March 26-April 1 data pushes
# ═══════════════════════════════════════════════════════════════
if log_files_found:
    print(f"\n\n{'='*80}")
    print("PART 3: SCANNING LOGS FOR MISSING WEEK DATA")
    print(f"{'='*80}")
    
    for lf, size, mtime in log_files_found:
        if size > 500 * 1024 * 1024:  # Skip files > 500MB
            print(f"\n  Skipping {lf} (too large: {size/1024/1024:.0f} MB)")
            continue
        
        print(f"\n  Scanning {lf}...")
        try:
            # Read in chunks and search for dates
            found_lines = []
            with open(lf, 'r', errors='replace') as f:
                for i, line in enumerate(f):
                    for d in MISSING_DATES:
                        if d in line and ('update_data' in line or 'DATA_PUSH' in line or 
                                          'CLIENT_DATA_PUSH' in line or 'push' in line.lower()):
                            found_lines.append((i+1, line.strip()[:200]))
                    
                    if i > 10000000:  # Cap at 10M lines
                        break
            
            if found_lines:
                print(f"    {len(found_lines)} relevant lines found!")
                for lineno, text in found_lines[:20]:
                    print(f"      Line {lineno}: {text}")
            else:
                # Just show last few lines for context
                try:
                    with open(lf, 'r', errors='replace') as f:
                        lines = f.readlines()
                        if lines:
                            print(f"    {len(lines)} total lines, last entries:")
                            for line in lines[-5:]:
                                print(f"      {line.strip()[:150]}")
                except:
                    pass
        except Exception as e:
            print(f"    Error reading: {e}")


# ═══════════════════════════════════════════════════════════════
# PART 4: data_history in current DB — get the LATEST version per client
# and check what we can restore
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PART 4: DATA_HISTORY IN CURRENT DB")
print(f"{'='*80}")

try:
    conn = sqlite3.connect(CURRENT_DB)
    conn.row_factory = sqlite3.Row
    
    total = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
    print(f"  Total rows: {total}")
    
    dist = conn.execute("""
        SELECT SUBSTR(created_at, 1, 10) as day, COUNT(*) as cnt 
        FROM data_history GROUP BY day ORDER BY day DESC
    """).fetchall()
    
    print(f"\n  Date distribution:")
    for r in dist:
        print(f"    {r['day']}: {r['cnt']} snapshots")
    
    # Show per-client version info
    versions = conn.execute("""
        SELECT client_id, COUNT(*) as cnt, MIN(version) as min_v, MAX(version) as max_v,
               MIN(created_at) as first, MAX(created_at) as last
        FROM data_history GROUP BY client_id ORDER BY max_v DESC
    """).fetchall()
    
    print(f"\n  Per-client summary ({len(versions)} clients):")
    for r in versions[:20]:
        print(f"    {r['client_id']:<35} versions {r['min_v']}-{r['max_v']} ({r['cnt']} snapshots) | {r['first'][:19]} → {r['last'][:19]}")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════════
# PART 5: If we recovered missing week history, RESTORE to clients_data
# ═══════════════════════════════════════════════════════════════
missing_week_data = [r for r in recovered_history if r.get('created_at', '')[:10] in MISSING_DATES]

if missing_week_data:
    print(f"\n\n{'='*80}")
    print("PART 5: RESTORING FROM RECOVERED DATA_HISTORY")
    print(f"{'='*80}")
    
    # Get the LATEST snapshot per client from the missing week
    latest_per_client = {}
    for r in missing_week_data:
        cid = r['client_id']
        ca = r.get('created_at', '')
        if cid not in latest_per_client or ca > latest_per_client[cid]['created_at']:
            latest_per_client[cid] = r
    
    print(f"  {len(latest_per_client)} clients with missing week snapshots")
    
    # Compare with current DB
    conn = sqlite3.connect(CURRENT_DB)
    conn.row_factory = sqlite3.Row
    
    import shutil
    backup_name = f"dashboard.db.pre_history_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = os.path.join(DASH_DIR, backup_name)
    shutil.copy2(CURRENT_DB, backup_path)
    print(f"  Backup: {backup_name}")
    
    data_cols = ['deals', 'positions', 'account', 'evaluations', 'statistics', 
                 'dropdown_options', 'identity']
    
    restored = 0
    skipped = 0
    
    for cid, snapshot in latest_per_client.items():
        # Check current data
        cur_row = conn.execute("SELECT * FROM clients_data WHERE client_id = ?", (cid,)).fetchone()
        
        if cur_row:
            cur_lu = cur_row['last_updated'] or ''
            snap_date = snapshot['created_at'][:10]
            
            # Only restore if the snapshot is newer than current data
            if snap_date > cur_lu[:10]:
                # Update with snapshot data
                updates = {}
                for col in data_cols:
                    if snapshot.get(col):
                        updates[col] = snapshot[col]
                
                if updates:
                    set_clause = ', '.join([f"{c} = ?" for c in updates.keys()])
                    values = list(updates.values()) + [cid]
                    conn.execute(f"UPDATE clients_data SET {set_clause}, last_updated = ? WHERE client_id = ?",
                                list(updates.values()) + [snapshot['created_at'], cid])
                    print(f"  RESTORED: {cid} from {snap_date} snapshot (was {cur_lu[:10]})")
                    restored += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        else:
            # Client doesn't exist in current DB — insert
            updates = {col: snapshot.get(col) for col in data_cols if snapshot.get(col)}
            updates['client_id'] = cid
            updates['last_updated'] = snapshot['created_at']
            
            col_names = ', '.join(updates.keys())
            placeholders = ', '.join(['?'] * len(updates))
            conn.execute(f"INSERT INTO clients_data ({col_names}) VALUES ({placeholders})", list(updates.values()))
            print(f"  ADDED: {cid} from {snapshot['created_at'][:10]} snapshot")
            restored += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n  SUMMARY: {restored} restored, {skipped} skipped (current was newer)")
else:
    print(f"\n\nNo missing week data found to restore.")
    print(f"The data_history rows from March 26-April 1 were likely stored in the WAL")
    print(f"that was truncated during cleanup.")


print(f"\n\n{'='*100}")
print("COMPLETE")
print(f"{'='*100}")
