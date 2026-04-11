import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Tables: clients_data, evaluations, daily_watermarks, waterlog_periods, etc.

# Check clients_data structure
cur.execute("PRAGMA table_info(clients_data)")
print("clients_data columns:", [r['name'] for r in cur.fetchall()])

cur.execute("PRAGMA table_info(evaluations)")
print("evaluations columns:", [r['name'] for r in cur.fetchall()])

# Find Chris Ream
for table in ['clients_data', 'evaluations']:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r['name'] for r in cur.fetchall()]
    for col in cols:
        if 'name' in col.lower() or 'client' in col.lower() or 'id' == col.lower():
            try:
                cur.execute(f"SELECT DISTINCT [{col}] FROM {table} WHERE [{col}] LIKE '%chris%' OR [{col}] LIKE '%ream%'")
                found = cur.fetchall()
                if found:
                    for f in found:
                        print(f"Found in {table}.{col}: {f[col]}")
            except:
                pass

# List all distinct client identifiers
print("\n--- All clients in clients_data ---")
cur.execute("SELECT DISTINCT client_id FROM clients_data")
for r in cur.fetchall():
    print(f"  {r['client_id']}")

conn.close()
