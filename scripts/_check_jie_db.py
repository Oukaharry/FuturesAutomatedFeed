"""Quick check of Jie's DB state."""
import sqlite3, json, os
DB = os.path.join('dashboard', 'dashboard.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT evaluations, statistics FROM clients_data WHERE client_id=?", ('Jiang Quang Huang',)).fetchone()
evals = json.loads(row['evaluations'] or '[]')
stats = json.loads(row['statistics'] or '{}')
print(f"DB rows: {len(evals)}")
print(f"DB EV: {stats.get('expected_value', 'N/A')}")
print(f"DB ev_tracking: {stats.get('ev_tracking', {})}")
if evals:
    last = evals[-1]
    print(f"Last row: {last.get('Prop Firm')} | {last.get('Account #')} | P1={last.get('Status P1')} | Fee={last.get('Fee')}")
    print(f"Row 426 check: {evals[425].get('Prop Firm') if len(evals) >= 426 else 'N/A'}")
conn.close()
