
import sqlite3
import os
import sys

# Define DB Path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.db')

def inspect_evaluations():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall()]
    print("Tables:", tables)
    
    if 'evaluations' not in tables: 
        print("❌ 'evaluations' table NOT found in DB. Checking for other potential tables...")
        # Check if maybe it's inside 'clients' blob data?
        if 'clients' in tables:
             print("Checking 'clients' table structure...")
             cursor.execute("PRAGMA table_info(clients)")
             for col in cursor.fetchall():
                 print(dict(col))
        return

    print("\n--- Clients Data Table Schema ---")
    cursor.execute("PRAGMA table_info(clients_data)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(columns)
    
    print("\n--- Listing Clients ---")
    try:
        # Select client_id and evaluations column
        cursor.execute("SELECT client_id, evaluations FROM clients_data")
        rows = cursor.fetchall()
        print(f"Total clients found: {len(rows)}")
        
        search_ids = ['60020', '74020', '80594']
        
        for row in rows:
            c_id = row['client_id']
            eval_json = row['evaluations']
            
            if not eval_json:
                print(f"Client {c_id}: No evaluations data (None/Empty)")
                continue

            # Decode JSON data
            try:
                import json
                evaluations = json.loads(eval_json)
                
                print(f"\nClient: {c_id} - {len(evaluations)} evaluations")
                
                # Check for our mysterious IDs inside this client's evaluations
                for eval_item in evaluations:
                    # Try various keys used for account number
                    acc_num = str(eval_item.get('Account Number', '')) or str(eval_item.get('account_number', ''))
                    
                    found_match = False
                    for s_id in search_ids:
                        if s_id in acc_num:
                            print(f"  ✅ FOUND MATCH: {s_id} in Acc: {acc_num} (Eval ID: {eval_item.get('id')})")
                            found_match = True
                            
                    if not found_match:
                         # Print un-matched account numbers just to see what they look like
                         # print(f"  - Unmatched Acc: '{acc_num}'")
                         pass
                    
                    if not acc_num.strip():
                         pass # print(f"  ⚠️  Empty Account Number in Eval ID: {eval_item.get('id')}")

            except Exception as e:
                print(f"  Error parsing evaluations JSON for {c_id}: {e}")
                
    except Exception as e:
        print(f"Error reading clients_data: {e}")

    conn.close()


if __name__ == "__main__":
    inspect_evaluations()
