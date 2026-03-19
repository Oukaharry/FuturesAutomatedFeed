"""Check Tyler Turner's payout date fields."""
from dashboard.database import get_client_data

data = get_client_data('Tyler Turner')
if not data:
    print("Tyler Turner: no local data")
    # Try searching
    from config.hierarchy import get_all_clients
    clients = get_all_clients()
    matches = [c for c in clients if 'tyler' in c.lower()]
    print(f"Similar names: {matches}")
else:
    evs = data.get('evaluations', [])
    print(f"Tyler Turner: {len(evs)} rows")
    for i, ev in enumerate(evs):
        acct = str(ev.get('Account #', '') or '') + str(ev.get('Account #.1', '') or '')
        if 'FTPROPLUS' in acct or 'Funding' in str(ev.get('Prop Firm', '')):
            date_keys = [k for k in ev.keys() if 'Date' in str(k) and not str(k).startswith('_')]
            print(f"  Row {i+1}: {ev.get('Prop Firm','')} | Acct: {acct}")
            print(f"    Date fields: { {k: ev[k] for k in date_keys if ev.get(k)} }")
            # Check payout columns specifically
            payout_keys = [k for k in ev.keys() if k in ('Date 1','Date 2','Date 3','Date 4','Payout 1','Payout 2','Payout 3','Payout 4')]
            print(f"    Payout cols: { {k: ev[k] for k in payout_keys if ev.get(k)} }")
            break
