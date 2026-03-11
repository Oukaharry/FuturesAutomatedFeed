import sys, os, json, sqlite3
sys.path.insert(0, '.')
from utils.data_processor import calculate_statistics
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
for cid in ['Chris', 'Ed', 'Nikki', 'Tyler']:
    row = conn.execute('SELECT evaluations, deals, account FROM clients_data WHERE client_id=?', (cid,)).fetchone()
    if not row: continue
    evals = json.loads(row['evaluations'] or '[]')
    deals = json.loads(row['deals'] or '[]')
    account = json.loads(row['account'] or '{}')
    stats = calculate_statistics(evals, deals if deals else None, account if account else None)
    ev = stats.get('expected_value', 'N/A')
    tracking = stats.get('ev_tracking', {})
    print(f"{cid:15s} EV={ev}  tracking={tracking}")
conn.close()
