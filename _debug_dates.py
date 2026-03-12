from dashboard.database import get_client_data

clients = ['Ed Schreiner', 'Joe Hickens', 'Wayne Ogolla', 'Steve Okok']
for c in clients:
    data = get_client_data(c)
    if data and 'evaluations' in data and data['evaluations']:
        evals = data['evaluations']
        print(f"=== {c} ({len(evals)} evals) ===")
        for i, ev in enumerate(evals[:5]):
            dp = ev.get('Date Purchased', 'MISSING_KEY')
            ds = ev.get('Date Started', 'MISSING_KEY')
            de = ev.get('Date Ended', 'MISSING_KEY')
            pf = ev.get('Prop Firm', '')
            print(f"  Row {i}: PF={pf}, DatePurch=[{dp}], DateStart=[{ds}], DateEnd=[{de}]")
        # Also show all keys from first eval
        print(f"  All keys: {list(evals[0].keys())}")
        break
