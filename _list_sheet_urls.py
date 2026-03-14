import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT client_id, identity FROM clients_data").fetchall()
for r in rows:
    identity = json.loads(r['identity'] or '{}')
    url = identity.get('sheet_url', '')
    if url:
        print(f"{r['client_id']}: {url[:80]}")
conn.close()
