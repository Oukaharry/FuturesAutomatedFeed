
import sqlite3
import json
import os

DB_PATH = 'dashboard/dashboard.db'

def inspect_client(client_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"Inspecting client: {client_id}")
    
    cursor.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (client_id,))
    row = cursor.fetchone()
    
    if row and row[0]:
        evals = json.loads(row[0])
        print(f"Found {len(evals)} evaluations.")
        # Print a few to check account numbers
        for i, ev in enumerate(evals[:10]):
            acc = ev.get('Account #')
            acc2 = ev.get('Account #.1')
            phase = ev.get('Status P1')
            print(f"Eval {i+1}: Account={acc}, {acc2}, Phase={phase}")
            
            # Check specifically for 4610
            if (acc and '4610' in str(acc)) or (acc2 and '4610' in str(acc2)):
                print(f"*** FOUND TARGET ACCOUNT in Eval {i+1}: {acc} / {acc2} ***")
                
        # Search all for target
        found = False
        for ev in evals:
             acc = ev.get('Account #')
             acc2 = ev.get('Account #.1')
             if (acc and '4610' in str(acc)) or (acc2 and '4610' in str(acc2)):
                 print(f"*** FOUND TARGET ACCOUNT (Full Search): {acc} / {acc2} - Status: {ev.get('Status P1')} ***")
                 found = True
        
        if not found:
            print("Target account 4610 NOT found in evaluations.")
            
    else:
        print("Client not found")
        
    conn.close()

if __name__ == "__main__":
    inspect_client("Jiang Quang Huang")
