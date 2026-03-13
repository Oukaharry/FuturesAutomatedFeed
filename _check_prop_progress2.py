from dashboard.database import get_connection
import json

with get_connection() as conn:
    cur = conn.cursor()
    
    # Check how many evaluations Ed has
    # Find the right table
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [r[0] for r in cur.fetchall()])
    
    # Check clients_data schema
    cur.execute("PRAGMA table_info(clients_data)")
    print("clients_data schema:", [r[1] for r in cur.fetchall()])
    
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    if row:
        data = row[0]
        evals = json.loads(data) if isinstance(data, str) else data
        if not isinstance(evals, list):
            evals = evals.get('evaluations', []) if isinstance(evals, dict) else []
        print(f"Ed has {len(evals)} evaluations")
        
        # Check what's at index 249
        if len(evals) > 249:
            ev249 = evals[249]
            prop_firm = ev249.get('Prop Firm', 'N/A')
            prop_day1 = ev249.get('Prop Day 1', 'N/A')
            print(f"  eval[249]: Prop Firm={prop_firm}, Prop Day 1={prop_day1}")
        else:
            print(f"  Index 249 out of range!")
            
        # Check what's at index 536
        if len(evals) > 536:
            ev536 = evals[536]
            prop_firm = ev536.get('Prop Firm', 'N/A')
            prop_day1 = ev536.get('Prop Day 1', 'N/A')
            print(f"  eval[536]: Prop Firm={prop_firm}, Prop Day 1={prop_day1}")
        else:
            print(f"  Index 536 out of range!")
        
        # Show last 10 evals indices
        print(f"\nLast 10 eval indices: {len(evals)-10} to {len(evals)-1}")
        for i in range(max(0, len(evals)-10), len(evals)):
            print(f"  [{i}]: Prop Firm={evals[i].get('Prop Firm','N/A')}, Prop Day 1={evals[i].get('Prop Day 1','N/A')}")
    
    # Also check schema of cell_notes
    cur.execute("PRAGMA table_info(cell_notes)")
    print("\ncell_notes schema:")
    for col in cur.fetchall():
        print(f"  {col}")
    
    # Check if row_index types are consistent
    cur.execute("SELECT DISTINCT typeof(row_index) FROM cell_notes")
    print(f"\nrow_index types: {[r[0] for r in cur.fetchall()]}")
