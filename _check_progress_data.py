"""Check if there's progress-like data anywhere in evaluations or other tables"""
import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
cur = conn.cursor()

# Check a few clients to see what data Chris has
cur.execute("SELECT client_id FROM clients_data LIMIT 10")
clients = [r[0] for r in cur.fetchall()]
print(f"First 10 clients: {clients}")

# Check Chris's data - look at a row that has farming data
for cid in ['Chris', 'Chris Ream']:
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (cid,))
    row = cur.fetchone()
    if row:
        evals = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        print(f"\n{cid}: {len(evals)} evaluations")
        # Find rows that have Prop Day data
        for i, ev in enumerate(evals[:20]):
            pd1 = ev.get('Prop Day 1', '')
            if pd1:
                print(f"  Row {i}: Prop Day 1={pd1}, Prop Day 2={ev.get('Prop Day 2','')}")
                # Check if there's any notes or progress keys
                progress_keys = [k for k in ev.keys() if 'rogress' in k.lower() or 'note' in k.lower() or '_notes' in k.lower()]
                if progress_keys:
                    print(f"    Progress/Note keys: {progress_keys}")
                    for pk in progress_keys:
                        print(f"      {pk} = {ev[pk]}")
        # Also check for _notes
        notes_count = sum(1 for ev in evals if '_notes' in ev and ev['_notes'])
        print(f"  Rows with _notes: {notes_count}")
    else:
        print(f"\n{cid}: NOT FOUND")

# Check what notes exist for Chris
for cid in ['Chris', 'Chris Ream']:
    cur.execute("SELECT COUNT(*) FROM cell_notes WHERE client_id = ?", (cid,))
    cnt = cur.fetchone()[0]
    print(f"\ncell_notes for '{cid}': {cnt}")

# Check ALL client_ids in cell_notes vs clients_data  
cur.execute("SELECT DISTINCT client_id FROM cell_notes")
note_clients = [r[0] for r in cur.fetchall()]
cur.execute("SELECT DISTINCT client_id FROM clients_data")
data_clients = [r[0] for r in cur.fetchall()]
print(f"\nClients with notes: {note_clients}")
print(f"Total clients in system: {len(data_clients)}")
print(f"Clients with data: {data_clients[:20]}")

conn.close()
