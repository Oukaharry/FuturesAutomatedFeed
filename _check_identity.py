from dashboard.database import get_connection
import json

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT identity FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    if row and row[0]:
        identity = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        print(json.dumps(identity, indent=2)[:1000])
    else:
        print("No identity data")
