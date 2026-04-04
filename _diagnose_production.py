"""
Production DB Diagnostic Script
Runs fast — every query has a 3-second timeout.
Paste entire file into PythonAnywhere console:
    python3 _diagnose_production.py
"""
import os, sys, signal

# Timeout helper (Unix only)
class TimeoutError(Exception): pass
def timeout_handler(signum, frame): raise TimeoutError()
signal.signal(signal.SIGALRM, timeout_handler)

DB_DIR = os.path.expanduser("~/MT5Dashboard/dashboard")
ROOT_DIR = os.path.expanduser("~/MT5Dashboard")

print("=" * 60)
print("  PRODUCTION DB DIAGNOSTIC REPORT")
print("=" * 60)

# 1. List all DB files
print("\n[1] DB FILES FOUND:")
for d in [DB_DIR, ROOT_DIR]:
    for f in sorted(os.listdir(d)):
        if 'dashboard.db' in f:
            fp = os.path.join(d, f)
            sz = os.path.getsize(fp)
            mb = sz / (1024 * 1024)
            label = " <-- APP USES THIS" if fp == os.path.join(DB_DIR, "dashboard.db") else ""
            print(f"  {fp}: {mb:.1f} MB{label}")

# 2. Check each DB file health (3s timeout each)
import sqlite3

db_files = []
for d in [DB_DIR, ROOT_DIR]:
    for f in sorted(os.listdir(d)):
        if f.startswith('dashboard.db') and not f.endswith(('-wal', '-shm')):
            db_files.append(os.path.join(d, f))

print(f"\n[2] HEALTH CHECK (3s timeout per file):")
healthy_with_data = []

for dbf in db_files:
    sz = os.path.getsize(dbf) / (1024 * 1024)
    name = os.path.basename(dbf)
    if sz == 0:
        print(f"  {name}: EMPTY (0 bytes) — skip")
        continue

    signal.alarm(3)
    try:
        conn = sqlite3.connect(dbf, timeout=2)
        r = conn.execute("PRAGMA quick_check(1)").fetchone()
        status = r[0] if r else "unknown"
        if status == "ok":
            # Count clients
            try:
                signal.alarm(3)
                cnt = conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
                print(f"  {name} ({sz:.1f} MB): HEALTHY — {cnt} clients")
                if cnt > 0:
                    healthy_with_data.append((dbf, cnt, sz))
            except Exception:
                print(f"  {name} ({sz:.1f} MB): HEALTHY — no clients_data table")
        else:
            # Corrupt but maybe readable
            print(f"  {name} ({sz:.1f} MB): CORRUPT — {status[:80]}")
            try:
                signal.alarm(3)
                cnt = conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
                print(f"    BUT clients_data readable: {cnt} clients")
                if cnt > 0:
                    healthy_with_data.append((dbf, cnt, sz))
            except Exception as e2:
                print(f"    clients_data NOT readable: {e2}")
        conn.close()
    except TimeoutError:
        print(f"  {name} ({sz:.1f} MB): TIMEOUT (hung >3s) — too corrupt/large")
    except Exception as e:
        print(f"  {name} ({sz:.1f} MB): ERROR — {e}")
    finally:
        signal.alarm(0)

# 3. Check active DB detail
active_db = os.path.join(DB_DIR, "dashboard.db")
print(f"\n[3] ACTIVE DB DETAIL ({os.path.basename(active_db)}):")
if os.path.exists(active_db) and os.path.getsize(active_db) > 0:
    signal.alarm(5)
    try:
        conn = sqlite3.connect(active_db, timeout=3)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in sorted(tables):
            signal.alarm(3)
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                print(f"  {t}: {cnt:,} rows")
            except TimeoutError:
                print(f"  {t}: TIMEOUT")
            except Exception as e:
                print(f"  {t}: ERROR — {e}")
        conn.close()
    except TimeoutError:
        print("  TIMEOUT connecting")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        signal.alarm(0)
else:
    print("  File missing or empty")

# 4. Disk space
print(f"\n[4] DISK SPACE:")
os.system("df -h ~ | tail -1")

# 5. Recommendation
print(f"\n[5] RECOMMENDATION:")
if healthy_with_data:
    best = max(healthy_with_data, key=lambda x: x[1])
    if best[0] == active_db:
        print(f"  Active DB has data ({best[1]} clients). Site should work.")
    else:
        print(f"  BEST SOURCE: {os.path.basename(best[0])} — {best[1]} clients, {best[2]:.1f} MB")
        print(f"  ACTION: Extract data from it into fresh DB using migration script")
else:
    print("  No DB with readable client data found.")
    print("  ACTION: Re-sync all data from Google Sheets")

print("\n" + "=" * 60)
print("  END OF DIAGNOSTIC")
print("=" * 60)
