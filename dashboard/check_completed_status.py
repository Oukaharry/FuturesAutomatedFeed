import json

try:
    with open('dashboard/dashboard_data.json', 'r') as f:
        data = json.load(f)

    print("Checking evaluations for 'Completed' status:")
    for client, cdata in data.get('clients_db', {}).items():
        evals = cdata.get('evaluations', [])
        for i, ev in enumerate(evals):
            s1 = str(ev.get('Status P1', '')).lower()
            s2 = str(ev.get('Status', '')).lower()
            
            if 'completed' in s1 or 'completed' in s2:
                print(f"Index {i}: Prop Firm={ev.get('Prop Firm')}, Account={ev.get('Account #')}, Status P1='{ev.get('Status P1')}', Status='{ev.get('Status')}'")

    print("\nChecking evaluations for 'Fail' status:")
    for client, cdata in data.get('clients_db', {}).items():
        evals = cdata.get('evaluations', [])
        for i, ev in enumerate(evals):
            s1 = str(ev.get('Status P1', '')).lower()
            s2 = str(ev.get('Status', '')).lower()
            
            if 'fail' in s1 or 'fail' in s2:
                # print(f"Index {i}: Prop Firm={ev.get('Prop Firm')}, Account={ev.get('Account #')}, Status P1='{ev.get('Status P1')}', Status='{ev.get('Status')}'")
                pass # Skipping verbose output for fail
            
except Exception as e:
    print(e)
