#!/usr/bin/env python3
"""
Server maintenance script — run from the project root on PythonAnywhere:
    python fix_db.py

1. Finds and deletes .corrupt. backup files and any other large DB copies
2. Repairs the main dashboard.db if corrupted (dump-rebuild or reinitialize)
3. Shows disk usage summary
"""
import os
import sys
import sqlite3
import shutil
import glob
from datetime import datetime

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard')
DB_PATH = os.path.join(DASHBOARD_DIR, 'dashboard.db')

def fmt_size(n):
    for u in ['B', 'KB', 'MB', 'GB']:
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def find_junk_files():
    """Find .corrupt backups, .new temp files, and other large DB copies.
    NEVER includes the main dashboard.db — only temp/backup copies."""
    patterns = [
        os.path.join(DASHBOARD_DIR, '*.corrupt.*'),
        os.path.join(DASHBOARD_DIR, '*.old_corrupt'),
        os.path.join(DASHBOARD_DIR, '*.new'),
        os.path.join(DASHBOARD_DIR, '*.rebuilt'),
        os.path.join(DASHBOARD_DIR, '*.pre_repair.*'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-journal'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-wal'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-shm'),
    ]
    # Also check project root for stray backup files
    root = os.path.dirname(DASHBOARD_DIR)
    patterns += [
        os.path.join(root, '*.corrupt.*'),
        os.path.join(root, '*.db.bak'),
    ]
    
    # Safety: explicitly protect the main database
    protected = {
        os.path.abspath(DB_PATH),
        os.path.abspath(os.path.join(DASHBOARD_DIR, 'dashboard.db')),
    }
    
    files = []
    for pat in patterns:
        for f in glob.glob(pat):
            if os.path.abspath(f) not in protected:
                files.append(f)
    return files

def check_integrity(db_path):
    """Returns True if database passes integrity check."""
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute('PRAGMA integrity_check').fetchone()
        conn.close()
        return result and result[0] == 'ok'
    except Exception as e:
        print(f"  Integrity check error: {e}")
        return False

def repair_db(db_path):
    """Table-by-table rescue — copies readable tables into a fresh DB.
    Much faster than iterdump on a large corrupt file."""
    new_path = db_path + '.rebuilt'
    
    print("  Rescuing data table-by-table...")
    try:
        src = sqlite3.connect(db_path)
        src.execute('PRAGMA journal_mode=OFF')
        src.execute('PRAGMA synchronous=OFF')
        
        # Get list of tables
        tables = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()]
        print(f"  Found tables: {', '.join(tables)}")
        
        # Create fresh destination with proper schema
        if os.path.exists(new_path):
            os.remove(new_path)
        
        sys.path.insert(0, os.path.dirname(DASHBOARD_DIR))
        from dashboard.database import init_database as _init_db
        
        # Temporarily override DB_PATH for init
        import dashboard.database as _db_mod
        _orig_path = _db_mod.DB_PATH
        _db_mod.DB_PATH = new_path
        _init_db()
        _db_mod.DB_PATH = _orig_path
        
        dst = sqlite3.connect(new_path)
        dst.execute('PRAGMA journal_mode=OFF')
        dst.execute('PRAGMA synchronous=OFF')
        
        total_rows = 0
        for table in tables:
            try:
                # Get column info from destination
                dst_cols = [r[1] for r in dst.execute(f"PRAGMA table_info([{table}])").fetchall()]
                if not dst_cols:
                    print(f"  SKIP {table} (not in schema)")
                    continue
                
                # Read all rows from source
                rows = src.execute(f"SELECT * FROM [{table}]").fetchall()
                src_cols = [d[0] for d in src.execute(f"SELECT * FROM [{table}] LIMIT 0").description]
                
                # Map source columns to destination columns
                common_cols = [c for c in src_cols if c in dst_cols]
                if not common_cols:
                    print(f"  SKIP {table} (no matching columns)")
                    continue
                
                col_indices = [src_cols.index(c) for c in common_cols]
                col_list = ', '.join(f'[{c}]' for c in common_cols)
                placeholders = ', '.join('?' * len(common_cols))
                
                mapped_rows = [tuple(row[i] for i in col_indices) for row in rows]
                dst.executemany(f"INSERT OR IGNORE INTO [{table}] ({col_list}) VALUES ({placeholders})", mapped_rows)
                dst.commit()
                
                total_rows += len(rows)
                print(f"  OK   {table}: {len(rows)} rows rescued")
            except Exception as e:
                print(f"  FAIL {table}: {e}")
        
        src.close()
        dst.close()
        
        if total_rows > 0:
            # Swap: rename corrupt file, put rebuilt in place
            os.replace(db_path, db_path + '.old_corrupt')
            os.replace(new_path, db_path)
            print(f"\n  Rescued {total_rows} total rows into fresh database")
            print(f"  Old corrupt file saved as: dashboard.db.old_corrupt")
            return True
        else:
            print("  No rows recovered")
            if os.path.exists(new_path):
                os.remove(new_path)
            return False
    except Exception as e:
        print(f"  Rescue failed: {e}")
        if os.path.exists(new_path):
            os.remove(new_path)
        return False

def reinitialize_db(db_path):
    """Delete and let the app recreate from scratch."""
    if os.path.exists(db_path):
        os.remove(db_path)
    # Import and run init_database
    sys.path.insert(0, os.path.dirname(DASHBOARD_DIR))
    from dashboard.database import init_database
    init_database()
    print("  Database reinitialized (empty, tables created)")

def main():
    print("=" * 60)
    print("  Database Maintenance Script")
    print("=" * 60)
    
    # --- Step 1: Find and delete junk files ---
    print("\n[1] Scanning for backup / temp files...")
    junk = find_junk_files()
    total_freed = 0
    
    if junk:
        for f in junk:
            size = os.path.getsize(f)
            print(f"  FOUND: {os.path.basename(f)}  ({fmt_size(size)})")
            total_freed += size
        
        print(f"\n  Total recoverable space: {fmt_size(total_freed)}")
        answer = input("  Delete all these files? [y/N]: ").strip().lower()
        if answer == 'y':
            for f in junk:
                try:
                    os.remove(f)
                    print(f"  DELETED: {os.path.basename(f)}")
                except Exception as e:
                    print(f"  FAILED to delete {os.path.basename(f)}: {e}")
            print(f"  Freed ~{fmt_size(total_freed)}")
        else:
            print("  Skipped deletion.")
    else:
        print("  No junk files found.")
    
    # --- Step 2: Check and repair main DB ---
    print(f"\n[2] Checking database: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("  Database file does not exist — reinitializing...")
        reinitialize_db(DB_PATH)
    else:
        size = os.path.getsize(DB_PATH)
        print(f"  Size: {fmt_size(size)}")
        
        # If DB is suspiciously large (>500MB), skip integrity check (too slow) and go to repair
        if size > 500 * 1024 * 1024:
            print(f"  Database is {fmt_size(size)} — abnormally large, likely corrupted/bloated")
            answer = input("  Rescue data into fresh compact DB? [y/N]: ").strip().lower()
            if answer == 'y':
                if repair_db(DB_PATH):
                    new_size = os.path.getsize(DB_PATH)
                    print(f"  Size reduced: {fmt_size(size)} -> {fmt_size(new_size)}")
                else:
                    print("  Rescue failed — reinitializing empty...")
                    reinitialize_db(DB_PATH)
            else:
                print("  Skipped.")
        elif check_integrity(DB_PATH):
            print("  Integrity: OK")
            
            # Vacuum to reclaim space
            answer = input("  Run VACUUM to compact the database? [y/N]: ").strip().lower()
            if answer == 'y':
                try:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute('VACUUM')
                    conn.close()
                    new_size = os.path.getsize(DB_PATH)
                    print(f"  Vacuumed: {fmt_size(size)} -> {fmt_size(new_size)}")
                except Exception as e:
                    print(f"  Vacuum failed: {e}")
        else:
            print("  Integrity: FAILED — database is corrupted")
            answer = input("  Rescue data into fresh DB? [y/N]: ").strip().lower()
            if answer == 'y':
                if repair_db(DB_PATH):
                    print("  Repair successful")
                else:
                    print("  Repair failed — reinitializing from scratch...")
                    reinitialize_db(DB_PATH)
            else:
                print("  Skipped repair.")
    
    # --- Step 3: Summary ---
    print(f"\n[3] Current disk usage:")
    if os.path.exists(DB_PATH):
        print(f"  dashboard.db: {fmt_size(os.path.getsize(DB_PATH))}")
    remaining = find_junk_files()
    if remaining:
        for f in remaining:
            print(f"  {os.path.basename(f)}: {fmt_size(os.path.getsize(f))}")
    
    print("\nDone. Reload the web app on PythonAnywhere after running this.")

if __name__ == '__main__':
    main()
