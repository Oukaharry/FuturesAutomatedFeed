import sqlite3
import json

DB_PATH = r"C:\Users\harry\Music\MT5HedgingEngine\dashboard\dashboard.db"
TARGETS = ["60020", "93499", "98517", "59555", "78380", "4220", "3443"]

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT client_id, evaluations FROM clients_data WHERE client_id = 'Jiang Quang Huang'")
row = cursor.fetchone()

if row:
    client_id, evals_json = row
    print(f"Checking {client_id} for targets: {TARGETS}")
    evals = json.loads(evals_json)
    for e in evals:
        acc = str(e.get('Account #', ''))
        acc1 = str(e.get('Account #.1', ''))
        
        for t in TARGETS:
            if t in acc or t in acc1:
                print(f"FOUND MATCH for {t}:")
                print(f"  Account #: '{acc}'")
                print(f"  Account #.1: '{acc1}'")
else:
    print("Client not found")

conn.close()