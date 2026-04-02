#!/usr/bin/env python3
"""
Restore data from the old corrupt 71GB database into the current clean database.

Usage on PythonAnywhere:
    python restore_data.py

This script:
1. Finds the old corrupt DB file (largest .corrupt.* or .old_corrupt file)
2. Reads each table from it one-by-one (skipping corrupt tables gracefully)
3. Inserts the recovered rows into the current clean dashboard.db
4. Does NOT delete the old file — you decide when to remove it
"""
import os
import sys
import sqlite3
import glob

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard')
DB_PATH = os.path.join(DASHBOARD_DIR, 'dashboard.db')

def fmt_size(n):
    for u in ['B', 'KB', 'MB', 'GB']:
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def find_old_db():
    """Find the largest corrupt/backup DB file that has the original data."""
    candidates = []
    
    # Check for backup files in dashboard dir
    for pat in ['*.corrupt.*', '*.old_corrupt', '*.pre_repair.*']:
        candidates.extend(glob.glob(os.path.join(DASHBOARD_DIR, pat)))
    
    # Also check if the main dashboard.db itself is the big one (not yet replaced)
    if os.path.exists(DB_PATH):
        size = os.path.getsize(DB_PATH)
        if size > 500 * 1024 * 1024:  # > 500MB means it's the corrupt original
            candidates.append(DB_PATH)
    
    if not candidates:
        return None
    
    # Return the largest file (most likely to have all the data)
    candidates.sort(key=lambda f: os.path.getsize(f), reverse=True)
    return candidates[0]

def main():
    print("=" * 60)
    print("  Data Restoration Script")
    print("=" * 60)
    
    # Step 1: Find the old DB with data
    print("\n[1] Looking for old database with data...")
    old_db = find_old_db()
    
    if not old_db:
        print("  ERROR: No old/corrupt database file found!")
        print("  Looked for: dashboard.db.corrupt.*, dashboard.db.old_corrupt")
        print("  If the file has a different name, pass it as argument:")
        print("    python restore_data.py /path/to/old_file.db")
        return
    
    # Allow user to specify path manually
    if len(sys.argv) > 1:
        old_db = sys.argv[1]
    
    old_size = os.path.getsize(old_db)
    print(f"  Found: {old_db}")
    print(f"  Size:  {fmt_size(old_size)}")
    
    is_same_file = os.path.abspath(old_db) == os.path.abspath(DB_PATH)
    
    # Step 2: Read tables from old DB
    print(f"\n[2] Reading tables from old database...")
    try:
        src = sqlite3.connect(old_db)
        src.execute('PRAGMA journal_mode=OFF')
        src.execute('PRAGMA synchronous=OFF')
    except Exception as e:
        print(f"  ERROR: Cannot open old DB: {e}")
        return
    
    tables = []
    try:
        tables = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()]
    except Exception as e:
        print(f"  ERROR: Cannot read table list: {e}")
        src.close()
        return
    
    print(f"  Found {len(tables)} tables: {', '.join(tables)}")
    
    # Read all recoverable data
    recovered = {}
    for table in tables:
        try:
            rows = src.execute(f"SELECT * FROM [{table}]").fetchall()
            cols = [d[0] for d in src.execute(f"SELECT * FROM [{table}] LIMIT 0").description]
            recovered[table] = {'cols': cols, 'rows': rows}
            print(f"  OK   {table}: {len(rows)} rows")
        except Exception as e:
            print(f"  FAIL {table}: {e}")
    
    src.close()
    
    total_rows = sum(len(v['rows']) for v in recovered.values())
    print(f"\n  Total recovered: {total_rows} rows across {len(recovered)} tables")
    
    if total_rows == 0:
        print("  Nothing to restore.")
        return
    
    # Step 3: Determine target DB
    if is_same_file:
        # The big file IS the current dashboard.db — we need to rebuild
        print(f"\n[3] The old data is in the current dashboard.db")
        print(f"    Will rebuild into a new clean file...")
        
        new_path = DB_PATH + '.restored'
        if os.path.exists(new_path):
            os.remove(new_path)
        
        # Initialize fresh DB with schema
        sys.path.insert(0, os.path.dirname(DASHBOARD_DIR))
        import dashboard.database as db_mod
        orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = new_path
        db_mod.init_database()
        db_mod.DB_PATH = orig_path
        
        dst = sqlite3.connect(new_path)
    else:
        # Separate files — insert into current dashboard.db
        print(f"\n[3] Restoring into: {DB_PATH}")
        new_path = None
        dst = sqlite3.connect(DB_PATH)
    
    dst.execute('PRAGMA journal_mode=OFF')
    dst.execute('PRAGMA synchronous=OFF')
    
    # Step 4: Insert data
    print(f"\n[4] Inserting recovered data...")
    for table, data in recovered.items():
        src_cols = data['cols']
        rows = data['rows']
        
        try:
            # Check which columns exist in destination
            dst_cols = [r[1] for r in dst.execute(f"PRAGMA table_info([{table}])").fetchall()]
            if not dst_cols:
                print(f"  SKIP {table}: table not in destination schema")
                continue
            
            # Map columns
            common_cols = [c for c in src_cols if c in dst_cols]
            if not common_cols:
                print(f"  SKIP {table}: no matching columns")
                continue
            
            col_indices = [src_cols.index(c) for c in common_cols]
            col_list = ', '.join(f'[{c}]' for c in common_cols)
            placeholders = ', '.join('?' * len(common_cols))
            
            mapped_rows = [tuple(row[i] for i in col_indices) for row in rows]
            
            # Clear existing data in destination table first
            existing = dst.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            if existing > 0 and len(rows) > existing:
                dst.execute(f"DELETE FROM [{table}]")
                print(f"  Cleared {existing} existing rows from {table}")
            
            dst.executemany(
                f"INSERT OR REPLACE INTO [{table}] ({col_list}) VALUES ({placeholders})",
                mapped_rows
            )
            dst.commit()
            print(f"  OK   {table}: {len(rows)} rows restored")
        except Exception as e:
            print(f"  FAIL {table}: {e}")
    
    dst.close()
    
    # Step 5: Swap files if needed
    if is_same_file and new_path:
        print(f"\n[5] Swapping files...")
        backup_name = DB_PATH + '.old_corrupt'
        os.rename(DB_PATH, backup_name)
        os.rename(new_path, DB_PATH)
        new_size = os.path.getsize(DB_PATH)
        print(f"  Old corrupt DB renamed to: {os.path.basename(backup_name)} ({fmt_size(old_size)})")
        print(f"  New clean DB: {fmt_size(new_size)}")
        print(f"\n  To free disk space, delete the old file:")
        print(f"    rm {backup_name}")
    else:
        new_size = os.path.getsize(DB_PATH)
        print(f"\n[5] Restoration complete. DB size: {fmt_size(new_size)}")
    
    # Verify
    print(f"\n[6] Verification:")
    conn = sqlite3.connect(DB_PATH)
    for table in recovered:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            print(f"  {table}: {count} rows")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")
    conn.close()
    
    print("\nDone! Reload the web app on PythonAnywhere.")

if __name__ == '__main__':
    main()
