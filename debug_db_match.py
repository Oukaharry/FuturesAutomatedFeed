import sqlite3
import json
import os
import sys

# Add parent dir to sys.path to import dashboard.app if needed, 
# but for now just raw DB access
sys.path.append(os.getcwd())

db_path = 'dashboard/dashboard.db'
client_name_query = 'Jiang Quang Huang'

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print(f"Searching for client: {client_name_query}")
cursor.execute("SELECT client_id, evaluations, account FROM clients_data WHERE client_id = ?", (client_name_query,))
row = cursor.fetchone()

if not row:
    print("Client not found by exact match, trying LIKE...")
    cursor.execute("SELECT client_id, evaluations, account FROM clients_data WHERE client_id LIKE ?", ('%' + client_name_query + '%',))
    row = cursor.fetchone()

if row:
    print(f"Found client: {row['client_id']}")
    evaluations = json.loads(row['evaluations'])
    account = json.loads(row['account'])
    print(f"Evaluations count: {len(evaluations)}")
    
    # Print sample evaluations to see account fields
    print("\n--- Sample Evaluations (first 3) ---")
    for i, ev in enumerate(evaluations[:3]):
        print(f"Eval {i}: Account #={ev.get('Account #')}, Account #.1={ev.get('Account #.1')}")

    # Print funded account info
    print(f"\n--- Funded Account Data ---")
    print(f"Account #: {account.get('Account #', 'N/A')}")
    print(f"Account #.1: {account.get('Account #.1', 'N/A')}")
    
    # Try searching for specific substrings
    substrings = ["23575", "60021", "26181"]
    print(f"\n--- Searching for substrings: {substrings} ---")
    
    for term in substrings:
        print(f"Searching for '{term}'...")
        count = 0
        for i, ev in enumerate(evaluations):
            acc = str(ev.get('Account #', ''))
            acc1 = str(ev.get('Account #.1', ''))
            
            if term in acc or term in acc1:
                print(f"  MATCH in Eval {i}: Account #='{acc}', Account #.1='{acc1}'")
                count += 1
        
        funded_acc = str(account.get('Account #', ''))
        funded_acc1 = str(account.get('Account #.1', ''))
        if term in funded_acc or term in funded_acc1:
             print(f"  MATCH in FUNDED: Account #='{funded_acc}', Account #.1='{funded_acc1}'")
             count += 1
             
        if count == 0:
            print(f"  No match found for '{term}'")

else:
    print("Client not found.")

conn.close()
