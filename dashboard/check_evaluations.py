import sqlite3
import json

DB_PATH = r"C:\Users\harry\Music\MT5HedgingEngine\dashboard\dashboard.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT client_id, evaluations FROM clients_data WHERE client_id = 'Jiang Quang Huang'")
row = cursor.fetchone()

if row:
    client_id, evals_json = row
    print(f"Evaluations for {client_id}:")
    try:
        evals = json.loads(evals_json)
        print(f"Total Evaluations: {len(evals)}")
        print("\nLast 30 Accounts (Newest):")
        # Reverse to show newest at bottom usually? Or assuming older at top?
        for i, e in enumerate(evals[-30:]):
            acc = e.get('Account #', '')
            acc1 = e.get('Account #.1', '')
            pf = e.get('Prop Firm', '')
            dp = e.get('Date Purchased', '')
            ds = e.get('Date Started', '')
            print(f"  Account: {acc} | DatePurchased: {dp} | DateStarted: {ds} | Firm: {pf}")
            
    except json.JSONDecodeError:
        print("  Error decoding JSON")
else:
    print("Client Jiang Quang Huang not found")

conn.close()