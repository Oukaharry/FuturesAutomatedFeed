import sqlite3
conn = sqlite3.connect('dashboard/dashboard.db')
rows = conn.execute("SELECT client_id, COUNT(id) FROM cell_notes GROUP BY client_id ORDER BY client_id").fetchall()
total = 0
for name, count in rows:
    print(f"  {name}: {count}")
    total += count
print(f"\nTotal: {total} notes across {len(rows)} clients")
