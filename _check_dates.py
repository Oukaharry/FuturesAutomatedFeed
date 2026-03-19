"""Check what date formats exist in client evaluation data."""
from dashboard.database import get_client_data

for client_name in ['Aaron', 'Reece', 'Chris']:
    data = get_client_data(client_name)
    if not data:
        print(f'{client_name}: no data')
        continue
    evs = data.get('evaluations', [])
    print(f'\n=== {client_name} ({len(evs)} rows) ===')
    
    date_fields = ['Date Purchased', 'Date Started', 'Date Ended', 
                   'Date Started.1', 'Date Ended.1',
                   'Date 1', 'Date 2', 'Date 3', 'Date 4']
    
    count = 0
    for i, ev in enumerate(evs):
        if ev.get('_deleted'):
            continue
        prop = str(ev.get('Prop Firm', '') or '').strip()
        if not prop:
            continue
        
        dates_found = {}
        for f in date_fields:
            v = ev.get(f, '')
            if v:
                dates_found[f] = v
        
        # Check farming progress keys
        farming = {}
        for k, v in ev.items():
            ks = str(k)
            if ('Prop Day' in ks or 'Hedge Day' in ks) and v and not ks.startswith('_'):
                farming[k] = v
        
        if dates_found or farming:
            print(f'  Row {i+1}: dates={dates_found}')
            if farming:
                items = list(farming.items())[:3]
                print(f'    farming(first 3)={dict(items)}')
            count += 1
            if count >= 5:
                break
    
    if count == 0:
        # Show keys for first row with data
        for i, ev in enumerate(evs):
            prop = str(ev.get('Prop Firm', '') or '').strip()
            if prop:
                keys = [k for k in ev.keys() if not str(k).startswith('_')][:30]
                print(f'  Row {i+1} keys: {keys}')
                break
        print('  NO DATE VALUES FOUND in any row')
