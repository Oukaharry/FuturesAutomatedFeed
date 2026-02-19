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
    cursor.execute("SELECT * FROM daily_watermarks LIMIT 5")
    rows = cursor.fetchall()
    print(f"Total rows in 'daily_watermarks': {len(rows)}")
    for row in rows:
        print(dict(row))
        
    cursor.execute("SELECT client_id, count(*) as count FROM daily_watermarks GROUP BY client_id")
    counts = cursor.fetchall()
    print("Counts per client:")
    for c in counts:
        print(f" - {c['client_id']}: {c['count']}")

except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
