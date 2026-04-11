import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# List all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r['name'] for r in cur.fetchall()]
print("Tables:", tables)

# Find client_id for Chris Ream in client_data
cur.execute("SELECT DISTINCT client_id FROM client_data WHERE client_id LIKE '%chris%' OR client_id LIKE '%ream%'")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"Found client_id: {r['client_id']}")
else:
    # List all distinct client_ids
    cur.execute("SELECT DISTINCT client_id FROM client_data")
    all_ids = [r['client_id'] for r in cur.fetchall()]
    print(f"\nAll client_ids ({len(all_ids)}):")
    for cid in all_ids:
        print(f"  {cid}")

conn.close()
