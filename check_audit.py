import sqlite3
import os

db_path = 'dashboard/dashboard.db'
if not os.path.exists(db_path):
    print("DB not found!")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
try:
    cursor.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    print("Recent Audit Logs:")
    for row in rows:
        print(f"[{row['timestamp']}] {row['action']} by {row['user_identifier']}: {row['details']}")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
