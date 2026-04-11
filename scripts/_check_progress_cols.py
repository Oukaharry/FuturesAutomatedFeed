"""Check if Prop Progress exists as actual evaluation data columns (not notes)"""
from dashboard.database import get_connection
import json

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    evals = json.loads(row[0]) if isinstance(row[0], str) else row[0]

    # Check the latest row (index 854, shown as #855)
    ev = evals[854]
    print("=== Eval index 854 (row #855) - Alpha Futures ===")
    print(f"Prop Firm: {ev.get('Prop Firm')}")
    
    # Check for any key containing 'Progress' or 'progress'
    progress_keys = [k for k in ev.keys() if 'rogress' in k.lower() or 'Progress' in k]
    print(f"Keys with 'Progress': {progress_keys}")
    for k in progress_keys:
        print(f"  {k} = {ev[k]}")
    
    # Check for Prop Day keys
    prop_day_keys = [k for k in ev.keys() if k.startswith('Prop Day')]
    print(f"\nProp Day keys: {prop_day_keys}")
    for k in sorted(prop_day_keys):
        print(f"  {k} = {ev[k]}")
    
    # Print ALL keys for this eval
    print(f"\nAll keys ({len(ev.keys())}):")
    for k in sorted(ev.keys()):
        v = ev[k]
        if v is not None and v != '' and v != 0:
            print(f"  {k} = {v}")
    
    # Also check a row known to have progress notes (249)
    ev249 = evals[249]
    print("\n=== Eval index 249 - Funding Ticks ===")
    progress_keys_249 = [k for k in ev249.keys() if 'rogress' in k.lower()]
    print(f"Keys with 'Progress': {progress_keys_249}")
    for k in progress_keys_249:
        print(f"  {k} = {ev249[k]}")
    
    # Check a middle row too (index 770 which has notes)
    if 770 < len(evals):
        ev770 = evals[770]
        print(f"\n=== Eval index 770 - {ev770.get('Prop Firm')} ===")
        progress_keys_770 = [k for k in ev770.keys() if 'rogress' in k.lower()]
        print(f"Keys with 'Progress': {progress_keys_770}")
        for k in progress_keys_770:
            print(f"  {k} = {ev770[k]}")
        prop_day_keys_770 = [k for k in ev770.keys() if k.startswith('Prop Day')]
        print(f"Prop Day keys: {sorted(prop_day_keys_770)}")
        for k in sorted(prop_day_keys_770):
            print(f"  {k} = {ev770[k]}")
