import json
import os

JSON_PATH = os.path.join(os.getcwd(), 'dashboard', 'dashboard_data.json')

def cleanup():
    if not os.path.exists(JSON_PATH):
        print(f"File not found: {JSON_PATH}")
        return

    with open(JSON_PATH, 'r') as f:
        data = json.load(f)
    
    clients_db = data.get('clients_db', {})
    
    # Check for Client1
    if 'Client1' in clients_db:
        client1_data = clients_db['Client1']
        evaluations = client1_data.get('evaluations', [])
        
        # Check if evaluations match Tsubasa's account MFFUEVSCL443135001
        is_tsubasa = False
        for ev in evaluations:
            if str(ev.get('Account #', '')).strip() == 'MFFUEVSCL443135001':
                is_tsubasa = True
                break
        
        if is_tsubasa:
            print("Found Client1 with Tsubasa's account number (MFFUEVSCL443135001). Removing...")
            del clients_db['Client1']
            
            # Save back
            with open(JSON_PATH, 'w') as f:
                json.dump(data, f, indent=4)
            print("Successfully removed Client1 from dashboard_data.json")
        else:
            print("Client1 exists but does not match Tsubasa's account number. Not removing automatically.")
            # Print first few accounts just in case
            for ev in evaluations[:3]:
                print(f"Account #: {ev.get('Account #')}")
    else:
        print("Client1 not found in dashboard_data.json")

    # Also check if 'Tsubasa' exists as a key
    if 'Tsubasa' in clients_db:
        print("Found 'Tsubasa' key. Removing...")
        del clients_db['Tsubasa']
        with open(JSON_PATH, 'w') as f:
            json.dump(data, f, indent=4)
        print("Successfully removed Tsubasa from dashboard_data.json")

if __name__ == '__main__':
    cleanup()
