"""
Delete Joe Hickens data from the PRODUCTION database on PythonAnywhere.

Run on the PythonAnywhere server:
    cd /home/ballerquotes/MT5Dashboard
    python delete_joe_data.py

This will delete all data for client_id='Joe' from:
  - clients_data
  - data_history
  - cell_notes
  - daily_watermarks
  - waterlog_periods
"""
import sqlite3
import os
import shutil
from datetime import datetime

# Production path on PythonAnywhere
DB_PATH = '/home/ballerquotes/MT5Dashboard/dashboard/dashboard.db'

# Fallback to local for testing
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

CLIENT_ID = 'Joe'

TABLES = [
    'clients_data',
    'data_history',
    'cell_notes',
    'daily_watermarks',
    'waterlog_periods',
]

def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    # Backup first
    backup_path = DB_PATH + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Show what will be deleted
    print(f"\n--- Data for client_id='{CLIENT_ID}' ---")
    total = 0
    for table in TABLES:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE client_id=?", (CLIENT_ID,))
            count = cursor.fetchone()[0]
            print(f"  {table}: {count} rows")
            total += count
        except Exception as e:
            print(f"  {table}: skipped ({e})")

    if total == 0:
        print("\nNo data found. Nothing to delete.")
        conn.close()
        return

    # Confirm
    confirm = input(f"\nDelete {total} total rows for '{CLIENT_ID}'? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Aborted.")
        conn.close()
        return

    # Delete
    print("\nDeleting...")
    for table in TABLES:
        try:
            cursor.execute(f"DELETE FROM {table} WHERE client_id=?", (CLIENT_ID,))
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"  {table}: {deleted} rows deleted")
        except Exception as e:
            print(f"  {table}: error - {e}")

    conn.commit()
    conn.close()
    print(f"\nDone. All '{CLIENT_ID}' data deleted.")
    print(f"Backup available at: {backup_path}")

if __name__ == '__main__':
    main()
