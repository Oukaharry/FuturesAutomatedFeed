import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT identity FROM clients_data WHERE client_id='Tyler'")
d = cur.fetchone()
conn.close()
if d and d['identity']:
    identity = json.loads(d['identity'])
    print(json.dumps(identity, indent=2))
else:
    print("No identity data found")
