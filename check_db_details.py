import sqlite3
import os

db_path = 'dashboard/dashboard.db'
if not os.path.exists(db_path):
    print("DB not found!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("PRAGMA table_info(daily_watermarks)")
    columns = cursor.fetchall()
    if columns:
        print("Table 'daily_watermarks' Structure:")
        for col in columns:
            print(f" - {col[1]} ({col[2]})")
    else:
        print("Table 'daily_watermarks' not found via PRAGMA.")
        
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
