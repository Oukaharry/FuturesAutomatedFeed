import sqlite3
import os

db_path = 'dashboard/dashboard.db'
if not os.path.exists(db_path):
    print("DB not found at:", db_path)
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_watermarks'")
    result = cursor.fetchone()
    print(f"Table 'daily_watermarks' check: {result}")
    
    if result:
        cursor.execute("PRAGMA table_info(daily_watermarks)")
        columns = cursor.fetchall()
        print("Columns:", [col[1] for col in columns])
        
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
