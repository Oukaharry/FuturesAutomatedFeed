
from dashboard.database import get_connection
import json

def check_ed():
    print("Checking database for client 'Ed'...")
    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()
        
        # Check clients_data
        cur.execute("SELECT id, client_id, length(evaluations) FROM clients_data WHERE client_id = 'Ed'")
        row = cur.fetchone()
        if row:
            print(f"Found in clients_data: ID={row[0]}, ClientID={row[1]}, EvalsLength={row[2]}")
            
            # Check actual content size
            cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
            eval_json = cur.fetchone()[0]
            try:
                evals = json.loads(eval_json)
                print(f"Parsed Evaluations Count: {len(evals)}")
                if evals:
                    print(f"First eval sample: {str(evals[0])[:100]}...")
            except Exception as e:
                print(f"JSON Parse Error: {e}")
        else:
            print("Client 'Ed' NOT FOUND in clients_data table.")
            # Check what clients ARE there
            cur.execute("SELECT client_id FROM clients_data")
            rows = cur.fetchall()
            print(f"Clients in DB ({len(rows)}):")
            for r in rows:
                print(f" - '{r[0]}'")

            
        # Check cell_notes
        cur.execute("SELECT COUNT(*) FROM cell_notes WHERE client_id = 'Ed'")
        count = cur.fetchone()[0]
        print(f"Found {count} notes for 'Ed' in cell_notes table.")

if __name__ == "__main__":
    check_ed()
