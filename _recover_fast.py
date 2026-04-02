#!/usr/bin/env python3
"""
OPTIMIZED recovery — 2-pass approach:
  Pass 1: Scan ONLY rowid + created_at (tiny query, no big JSON blobs)
  Pass 2: Fetch full data ONLY for missing week rows

Run: python3 _recover_fast.py
"""
import os, sys, json, sqlite3
from datetime import datetime
from collections import defaultdict

DASH_DIR   = os.path.expanduser('~/MT5Dashboard/dashboard')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')
CURRENT_DB = os.path.join(DASH_DIR, 'dashboard.db')

MISSING_DATES = {'2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
                 '2026-03-30', '2026-03-31', '2026-04-01'}

print("=" * 100)
print("FAST 2-PASS RECOVERY FROM data_history")
print(f"Time: {datetime.now()}")
print("=" * 100)

conn = sqlite3.connect(f'file:{CORRUPT_DB}?immutable=1', uri=True)

# ═══════════════════════════════════════════════════════════════
# PASS 1: Lightweight scan — only rowid, client_id, created_at
# ═══════════════════════════════════════════════════════════════
print(f"\nPASS 1: Lightweight scan of {98713} rowids...")
print(f"  (Only fetching rowid, client_id, created_at — no big JSON)")

date_dist = defaultdict(int)
missing_week_rowids = []  # (rowid, client_id, created_at)
all_dates = defaultdict(list)
recovered = 0
errors = 0

for rid in range(1, 98714):
    try:
        row = conn.execute(
            "SELECT rowid, client_id, created_at FROM data_history WHERE rowid = ?", 
            (rid,)
        ).fetchone()
        if row:
            recovered += 1
            rowid, cid, ca = row
            day = ca[:10] if ca else '?'
            date_dist[day] += 1
            
            if day in MISSING_DATES:
                missing_week_rowids.append((rowid, cid, ca))
            
            all_dates[day].append((rowid, cid, ca))
    except sqlite3.DatabaseError:
        errors += 1
        continue
    
    if rid % 10000 == 0:
        mw = len(missing_week_rowids)
        print(f"    ...{rid}/98713 — {recovered} readable, {errors} corrupt, {mw} missing-week")

print(f"\n  PASS 1 COMPLETE:")
print(f"    Total readable: {recovered}")
print(f"    Corrupt rowids: {errors}")
print(f"    Missing week rows: {len(missing_week_rowids)}")

print(f"\n  Date distribution:")
for d in sorted(date_dist.keys()):
    flag = " *** MISSING WEEK!" if d in MISSING_DATES else ""
    print(f"    {d}: {date_dist[d]:>5} snapshots{flag}")


# ═══════════════════════════════════════════════════════════════
# PASS 2: Fetch FULL data only for missing week rows
# ═══════════════════════════════════════════════════════════════
if missing_week_rowids:
    print(f"\n{'='*80}")
    print(f"PASS 2: Fetching FULL data for {len(missing_week_rowids)} missing week rows")
    print(f"{'='*80}")
    
    full_snapshots = []
    fetch_errors = 0
    
    for rowid, cid, ca in missing_week_rowids:
        try:
            row = conn.execute("SELECT * FROM data_history WHERE rowid = ?", (rowid,)).fetchone()
            if row:
                cols = [desc[0] for desc in conn.execute("PRAGMA table_info(data_history)").fetchall()]
                # Build dict manually
                d = {}
                for i, col_info in enumerate(conn.execute("PRAGMA table_info(data_history)").fetchall()):
                    d[col_info[1]] = row[i]
                full_snapshots.append(d)
                
                has_evals = bool(d.get('evaluations'))
                has_stats = bool(d.get('statistics'))
                has_deals = bool(d.get('deals'))
                print(f"    ✓ rowid {rowid}: {cid} @ {ca} | evals={has_evals} stats={has_stats} deals={has_deals}")
        except sqlite3.DatabaseError as e:
            fetch_errors += 1
            print(f"    ✗ rowid {rowid}: {cid} @ {ca} — ERROR: {e}")
            continue
    
    print(f"\n  Fetched: {len(full_snapshots)} complete snapshots, {fetch_errors} errors")
    
    # Group by client, keep latest per client
    latest_per_client = {}
    for snap in full_snapshots:
        cid = snap['client_id']
        ca = snap.get('created_at', '')
        if cid not in latest_per_client or ca > latest_per_client[cid]['created_at']:
            latest_per_client[cid] = snap
    
    print(f"  Unique clients with missing week data: {len(latest_per_client)}")
    for cid, snap in sorted(latest_per_client.items()):
        print(f"    {cid:<40} latest={snap['created_at']}")
    
    # ═══════════════════════════════════════════════════════════════
    # RESTORE to current DB
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print(f"RESTORING {len(latest_per_client)} clients from missing week snapshots")
    print(f"{'='*80}")
    
    import shutil
    backup_name = f"dashboard.db.pre_history_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(CURRENT_DB, os.path.join(DASH_DIR, backup_name))
    print(f"  Backup: {backup_name}")
    
    cur_conn = sqlite3.connect(CURRENT_DB)
    cur_conn.row_factory = sqlite3.Row
    
    data_cols = ['deals', 'positions', 'account', 'evaluations', 'statistics', 
                 'dropdown_options', 'identity']
    
    restored = 0
    skipped = 0
    
    for cid, snapshot in latest_per_client.items():
        cur_row = cur_conn.execute("SELECT last_updated FROM clients_data WHERE client_id = ?", (cid,)).fetchone()
        snap_date = snapshot.get('created_at', '')[:10]
        
        if cur_row:
            cur_lu = cur_row['last_updated'] or ''
            # Only restore if snapshot is from the missing week AND newer than current
            if snap_date > cur_lu[:10]:
                updates = {col: snapshot[col] for col in data_cols if snapshot.get(col)}
                if updates:
                    set_clause = ', '.join([f"{c} = ?" for c in updates.keys()])
                    vals = list(updates.values()) + [snapshot['created_at'], cid]
                    cur_conn.execute(
                        f"UPDATE clients_data SET {set_clause}, last_updated = ? WHERE client_id = ?",
                        vals
                    )
                    print(f"  RESTORED: {cid} ← {snap_date} (was {cur_lu[:10]})")
                    restored += 1
                else:
                    print(f"  SKIP: {cid} — snapshot has no data columns")
                    skipped += 1
            else:
                print(f"  SKIP: {cid} — current ({cur_lu[:10]}) >= snapshot ({snap_date})")
                skipped += 1
        else:
            # New client
            updates = {col: snapshot[col] for col in data_cols if snapshot.get(col)}
            updates['client_id'] = cid
            updates['last_updated'] = snapshot['created_at']
            col_names = ', '.join(updates.keys())
            placeholders = ', '.join(['?'] * len(updates))
            cur_conn.execute(f"INSERT INTO clients_data ({col_names}) VALUES ({placeholders})", 
                           list(updates.values()))
            print(f"  ADDED: {cid} ← {snap_date} (new client)")
            restored += 1
    
    cur_conn.commit()
    cur_conn.close()
    
    print(f"\n  RESULT: {restored} restored, {skipped} skipped")

else:
    print(f"\n  NO missing week rows found in data_history.")
    print(f"  All data_history entries from March 26-April 1 were in the WAL.")
    
    # Show what we DO have — maybe latest March 25 snapshots are useful
    print(f"\n  Latest available dates:")
    for d in sorted(date_dist.keys(), reverse=True)[:5]:
        count = date_dist[d]
        print(f"    {d}: {count} snapshots")
        if d == '2026-03-25':
            # Show client breakdown
            for rowid, cid, ca in all_dates[d][:10]:
                print(f"      rowid {rowid}: {cid} @ {ca}")

conn.close()

print(f"\n{'='*100}")
print("DONE")
print(f"{'='*100}")
