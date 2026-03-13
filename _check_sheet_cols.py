"""Check the raw Google Sheet column structure to see if Prop Progress exists as sheet columns"""
from dashboard.database import get_connection
import json

# Check if there's any saved sheet URL or column info
with get_connection() as conn:
    cur = conn.cursor()
    
    # Get Ed's raw evaluation data and check all keys across a few evals
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    evals = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    
    # Collect all unique keys across all evaluations
    all_keys = set()
    for ev in evals:
        all_keys.update(ev.keys())
    
    print("All unique keys across Ed's evaluations:")
    for k in sorted(all_keys):
        print(f"  {k}")
    
    print(f"\nTotal unique keys: {len(all_keys)}")
    
    # Check specifically for anything with 'Progress'
    progress_keys = [k for k in all_keys if 'rogress' in k.lower()]
    print(f"\nKeys containing 'Progress': {progress_keys}")
