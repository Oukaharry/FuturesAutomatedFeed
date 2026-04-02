#!/usr/bin/env python3
"""
Find YESTERDAY's data (April 1, 2026 end-of-day state).
Compares last_updated timestamps and data_history snapshots across all DBs.

The best data = the state of each client as it was on April 1 before today's corruption.

Run: python3 _find_yesterday.py
"""
import os, sys, json, sqlite3
from datetime import datetime

DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB     = os.path.join(DASH_DIR, 'dashboard.db')
CORRUPT_DB = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')
BACKUP_DB  = os.path.join(DASH_DIR, 'dashboard.db.backup_20260311_103843')

def connect(path, label=""):
    for method_name, fn in [
        ('immutable', lambda: sqlite3.connect(f'file:{path}?immutable=1', uri=True)),
        ('normal',    lambda: sqlite3.connect(path, timeout=30)),
    ]:
        try:
            conn = fn()
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1")
            return conn
        except:
            continue
    return None

def get_columns(conn, table):
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except:
        return []

print("=" * 100)
print("FINDING YESTERDAY'S DATA (April 1 end-of-day state)")
print(f"Time: {datetime.now()}")
print("=" * 100)

# ═══════════════════════════════════════════════════════════════
# STEP 1: Check last_updated for ALL clients in ALL DBs
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("STEP 1: CLIENT last_updated TIMESTAMPS")
print(f"{'='*100}")

dbs = {}
for label, path in [('current', CUR_DB), ('corrupt_48GB', CORRUPT_DB), ('backup_0311', BACKUP_DB)]:
    if not os.path.exists(path):
        print(f"  {label}: FILE NOT FOUND")
        continue
    conn = connect(path, label)
    if not conn:
        print(f"  {label}: CANNOT CONNECT")
        continue
    dbs[label] = conn

# Gather last_updated per client per DB
all_clients_data = {}  # {client_id: {db_label: last_updated}}

for label, conn in dbs.items():
    try:
        rows = conn.execute("SELECT client_id, last_updated FROM clients_data ORDER BY client_id").fetchall()
        for r in rows:
            cid = r['client_id']
            lu = r['last_updated']
            if cid not in all_clients_data:
                all_clients_data[cid] = {}
            all_clients_data[cid][label] = lu
    except Exception as e:
        print(f"  {label}: Error reading last_updated — {e}")

# Print comparison
print(f"\n{'Client':<30} {'Current DB last_updated':<30} {'Corrupt 48GB last_updated':<30} {'Backup 0311':<30} {'Best':<10}")
print("-" * 130)

best_source = {}  # {client_id: 'current' or 'corrupt_48GB'}

for cid in sorted(all_clients_data.keys()):
    data = all_clients_data[cid]
    cur_lu = data.get('current', '-')
    cor_lu = data.get('corrupt_48GB', '-')
    bak_lu = data.get('backup_0311', '-')
    
    # Determine which has the best (most recent but NOT from today Apr 2) data
    # We want the latest timestamp that is from Apr 1 or earlier
    best = "?"
    best_ts = None
    
    for src, ts in [('current', cur_lu), ('corrupt_48GB', cor_lu), ('backup_0311', bak_lu)]:
        if ts == '-' or not ts:
            continue
        # Check if this is from before April 2
        try:
            if '2026-04-02' in str(ts):
                # Today's data — we want yesterday's instead
                continue
            # Valid pre-today timestamp
            if best_ts is None or str(ts) > str(best_ts):
                best_ts = ts
                best = src
        except:
            pass
    
    # If no pre-today data found, just use the latest
    if best == "?":
        for src, ts in [('current', cur_lu), ('corrupt_48GB', cor_lu)]:
            if ts != '-' and ts:
                if best_ts is None or str(ts) > str(best_ts):
                    best_ts = ts
                    best = src
    
    best_source[cid] = best
    
    flag = ""
    if best == 'corrupt_48GB':
        flag = " <<<"
    elif cid in data and 'corrupt_48GB' not in data:
        flag = " (only current)"
    
    print(f"{cid:<30} {str(cur_lu):<30} {str(cor_lu):<30} {str(bak_lu):<30} {best:<12}{flag}")

# Summary
corrupt_better = [c for c, s in best_source.items() if s == 'corrupt_48GB']
current_better = [c for c, s in best_source.items() if s == 'current']
print(f"\n{'─'*100}")
print(f"SUMMARY:")
print(f"  Corrupt 48GB is better for: {len(corrupt_better)} clients")
print(f"  Current DB is better for:   {len(current_better)} clients")
if corrupt_better:
    print(f"\n  Clients where corrupt has yesterday's data:")
    for c in corrupt_better:
        print(f"    {c}: corrupt={all_clients_data[c].get('corrupt_48GB')}, current={all_clients_data[c].get('current', '-')}")


# ═══════════════════════════════════════════════════════════════
# STEP 2: Check data_history for yesterday's snapshots
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 2: DATA_HISTORY TABLE — looking for yesterday's snapshots")
print(f"{'='*100}")

for label, conn in dbs.items():
    print(f"\n  --- {label} ---")
    cols = get_columns(conn, 'data_history')
    print(f"  Columns: {cols}")
    
    if not cols:
        print(f"  Table does not exist")
        continue
    
    try:
        total = conn.execute("SELECT COUNT(*) FROM data_history").fetchone()[0]
        print(f"  Total rows: {total}")
    except Exception as e:
        print(f"  Error counting: {e}")
        continue
    
    # Find the right timestamp/date column
    time_col = None
    for candidate in ['timestamp', 'created_at', 'date', 'updated_at', 'snapshot_time', 'last_updated']:
        if candidate in cols:
            time_col = candidate
            break
    
    if not time_col:
        # Try to read a sample row to see what columns have date-like values
        print(f"  No obvious time column. Sampling rows...")
        try:
            sample = conn.execute("SELECT * FROM data_history LIMIT 3").fetchall()
            for i, row in enumerate(sample):
                print(f"    Row {i}:")
                for col in cols:
                    val = str(row[col])[:80] if row[col] else 'NULL'
                    print(f"      {col}: {val}")
        except Exception as e:
            print(f"    Error sampling: {e}")
        continue
    
    print(f"  Using time column: {time_col}")
    
    # Check for April 1 data
    try:
        for d in ['2026-04-01', '2026-03-31', '2026-03-30', '2026-03-29', '2026-03-28', '2026-03-27', '2026-03-26', '2026-03-25']:
            c = conn.execute(f"SELECT COUNT(*) FROM data_history WHERE {time_col} LIKE ?", (f"{d}%",)).fetchone()[0]
            if c > 0:
                print(f"    {d}: {c} snapshots!")
                # Show details
                client_col = 'client_id' if 'client_id' in cols else None
                if client_col:
                    details = conn.execute(
                        f"SELECT {client_col}, {time_col} FROM data_history WHERE {time_col} LIKE ? ORDER BY {time_col} DESC LIMIT 10",
                        (f"{d}%",)
                    ).fetchall()
                    for r in details:
                        print(f"      {r[0]} — {r[1]}")
    except Exception as e:
        print(f"    Error querying: {e}")
    
    # Also get the most recent entries regardless of date
    print(f"\n  Most recent data_history entries:")
    try:
        # Try ordering by the time column or by rowid desc
        try:
            recent = conn.execute(f"SELECT * FROM data_history ORDER BY {time_col} DESC LIMIT 10").fetchall()
        except:
            recent = conn.execute(f"SELECT * FROM data_history ORDER BY rowid DESC LIMIT 10").fetchall()
        
        for row in recent:
            summary = {}
            for col in cols[:6]:
                val = row[col]
                if val:
                    summary[col] = str(val)[:60]
                else:
                    summary[col] = 'NULL'
            print(f"    {summary}")
    except Exception as e:
        print(f"    Error: {e}")


# ═══════════════════════════════════════════════════════════════
# STEP 3: Check audit_log for yesterday's DATA_PUSH entries
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 3: AUDIT LOG — yesterday's data push activity")
print(f"{'='*100}")

for label, conn in dbs.items():
    print(f"\n  --- {label} ---")
    cols = get_columns(conn, 'audit_log')
    print(f"  Columns: {cols}")
    
    if not cols:
        continue
    
    # Find time column
    time_col = None
    for c in ['timestamp', 'created_at', 'date', 'time']:
        if c in cols:
            time_col = c
            break
    
    if not time_col:
        print(f"  No time column found")
        # Sample
        try:
            sample = conn.execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT 3").fetchall()
            for i, row in enumerate(sample):
                print(f"    Row {i}:")
                for col in cols:
                    val = str(row[col])[:80] if row[col] else 'NULL'
                    print(f"      {col}: {val}")
        except Exception as e:
            print(f"    Error sampling: {e}")
        continue
    
    # Find action column
    action_col = None
    for c in ['action', 'event', 'type', 'activity']:
        if c in cols:
            action_col = c
            break
    
    # Check for yesterday's entries
    for d in ['2026-04-01', '2026-03-31', '2026-03-30', '2026-03-25']:
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM audit_log WHERE {time_col} LIKE ?", (f"{d}%",)).fetchone()[0]
            if total == 0:
                continue
            
            print(f"\n    {d}: {total} total audit entries")
            
            # Count by action
            if action_col:
                try:
                    actions = conn.execute(f"""
                        SELECT {action_col}, COUNT(*) as cnt 
                        FROM audit_log WHERE {time_col} LIKE ?
                        GROUP BY {action_col} ORDER BY cnt DESC
                    """, (f"{d}%",)).fetchall()
                    for a in actions:
                        print(f"      {a[0]}: {a[1]}")
                except:
                    pass
            
            # Show latest entries
            try:
                det_col = 'details' if 'details' in cols else ('description' if 'description' in cols else None)
                uid_col = 'user_id' if 'user_id' in cols else ('client_id' if 'client_id' in cols else None)
                
                sel = f"{time_col}"
                if action_col: sel += f", {action_col}"
                if uid_col: sel += f", {uid_col}"
                if det_col: sel += f", {det_col}"
                
                entries = conn.execute(f"""
                    SELECT {sel} FROM audit_log 
                    WHERE {time_col} LIKE ?
                    ORDER BY {time_col} DESC LIMIT 10
                """, (f"{d}%",)).fetchall()
                
                print(f"    Latest entries on {d}:")
                for e in entries:
                    parts = []
                    for c in e.keys():
                        val = str(e[c])[:60] if e[c] else ''
                        parts.append(f"{c}={val}")
                    print(f"      {' | '.join(parts)}")
            except:
                pass
        except Exception as e:
            print(f"    {d}: Error — {e}")


# ═══════════════════════════════════════════════════════════════
# STEP 4: Direct comparison — which clients have Apr 1 last_updated?
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*100}")
print("STEP 4: CLIENTS WITH APRIL 1 / MARCH 31 last_updated (= yesterday's state)")
print(f"{'='*100}")

for label, conn in dbs.items():
    print(f"\n  --- {label} ---")
    try:
        for d in ['2026-04-01', '2026-03-31', '2026-03-30', '2026-03-29', '2026-03-28', '2026-03-27', '2026-03-26', '2026-03-25']:
            rows = conn.execute(
                "SELECT client_id, last_updated FROM clients_data WHERE last_updated LIKE ? ORDER BY last_updated DESC",
                (f"{d}%",)
            ).fetchall()
            if rows:
                print(f"    {d}: {len(rows)} clients last updated on this date")
                for r in rows[:10]:
                    print(f"      {r['client_id']:<30} — {r['last_updated']}")
                if len(rows) > 10:
                    print(f"      ... and {len(rows)-10} more")
    except Exception as e:
        print(f"    Error: {e}")
    
    # Also show the overall last_updated distribution
    print(f"\n    last_updated distribution:")
    try:
        dist = conn.execute("""
            SELECT SUBSTR(last_updated, 1, 10) as day, COUNT(*) as cnt 
            FROM clients_data 
            GROUP BY day 
            ORDER BY day DESC
        """).fetchall()
        for r in dist:
            print(f"      {r['day']}: {r['cnt']} clients")
    except Exception as e:
        print(f"      Error: {e}")


print(f"\n\n{'='*100}")
print("SEARCH COMPLETE")
print(f"{'='*100}")
