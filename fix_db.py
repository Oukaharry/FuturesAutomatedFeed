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
    """Find .corrupt backups, .new temp files, and other large DB copies."""
    patterns = [
        os.path.join(DASHBOARD_DIR, '*.corrupt.*'),
        os.path.join(DASHBOARD_DIR, '*.new'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-journal'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-wal'),
        os.path.join(DASHBOARD_DIR, 'dashboard.db-shm'),
    ]
    # Also check project root for stray DB files
    root = os.path.dirname(DASHBOARD_DIR)
    patterns += [
        os.path.join(root, '*.corrupt.*'),
        os.path.join(root, '*.db.bak'),
        os.path.join(root, 'dashboard.db.*'),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
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
    """Attempt dump-rebuild. Returns True on success."""
    backup = db_path + '.pre_repair.' + datetime.now().strftime('%Y%m%d_%H%M%S')
    new_path = db_path + '.rebuilt'
    
    print(f"  Backing up corrupt DB to: {os.path.basename(backup)}")
    shutil.copy2(db_path, backup)
    
    print("  Attempting dump-rebuild...")
    try:
        src = sqlite3.connect(db_path)
        lines = []
        try:
            for line in src.iterdump():
                lines.append(line)
        except Exception as e:
            print(f"  Partial dump (recovered {len(lines)} statements): {e}")
        finally:
            src.close()
        
        if lines:
            dst = sqlite3.connect(new_path)
            dst.executescript('\n'.join(lines))
            dst.close()
            os.replace(new_path, db_path)
            print(f"  Rebuilt database from {len(lines)} SQL statements")
            return True
        else:
            print("  No data recoverable from dump")
            return False
    except Exception as e:
        print(f"  Dump-rebuild failed: {e}")
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
        
        if check_integrity(DB_PATH):
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
            answer = input("  Attempt repair? [y/N]: ").strip().lower()
            if answer == 'y':
                if repair_db(DB_PATH):
                    if check_integrity(DB_PATH):
                        print("  Repair successful — integrity OK")
                    else:
                        print("  Repair produced invalid DB — reinitializing...")
                        reinitialize_db(DB_PATH)
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
