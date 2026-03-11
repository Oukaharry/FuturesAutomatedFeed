import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT client_id FROM clients_data').fetchall():
    evals = json.loads(conn.execute('SELECT evaluations FROM clients_data WHERE client_id=?', (r['client_id'],)).fetchone()['evaluations'] or '[]')
    stats = json.loads(conn.execute('SELECT statistics FROM clients_data WHERE client_id=?', (r['client_id'],)).fetchone()['statistics'] or '{}')
    ev = stats.get('expected_value', 'N/A')
    print(f"{r['client_id']:25s}  rows={len(evals):4d}  EV={ev}")
conn.close()
