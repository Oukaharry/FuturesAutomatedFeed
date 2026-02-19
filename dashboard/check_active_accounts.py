import json

try:
    with open('dashboard/dashboard_data.json', 'r') as f:
        data = json.load(f)

    print("Checking evaluations that are NOT Failed AND NOT Completed:")
    count = 0
    for client, cdata in data.get('clients_db', {}).items():
        evaluations = cdata.get('evaluations', [])
        for i, ev in enumerate(evaluations):
            s1 = str(ev.get('Status P1', '')).lower()
            s2 = str(ev.get('Status', '')).lower()
            
            is_active_1 = 'fail' not in s1 and 'breach' not in s1 and 'delete' not in s1 and 'closed' not in s1
            is_active_2 = 'fail' not in s2 and 'breach' not in s2 and 'delete' not in s2 and 'closed' not in s2 and 'completed' not in s2
            
            # Additional check: If Status is "-", check if Status P1 is passed
            if s2 == '-':
                # It is active if P1 is not failed
                is_active = is_active_1
            else:
                # If there is a status for funded phase, it drives the show
                is_active = is_active_2

            if is_active:
                count += 1
                if count <= 20:
                    print(f"Index {i}: Prop Firm={ev.get('Prop Firm')}, Account={ev.get('Account #')}, Status P1='{ev.get('Status P1')}', Status='{ev.get('Status')}'")

    print(f"Total Active Accounts found: {count}")
    
except Exception as e:
    print(e)
