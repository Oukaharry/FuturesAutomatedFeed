import sqlite3
import json
import os
import sys

# Find DB path
DB_PATH = 'dashboard/dashboard.db'

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("Searching for accounts...")
cursor.execute("SELECT client_id, evaluations FROM clients_data")
rows = cursor.fetchall()

found_accounts = []
found_see_note = []

target_ids = ["64959889", "58082198", "9889", "2198"]

for row in rows:
    client_id = row['client_id']
    try:
        evals = json.loads(row['evaluations'])
    except:
        continue
    
    for idx, ev in enumerate(evals):
        acc = str(ev.get('Account #', '')).strip()
        acc1 = str(ev.get('Account #.1', '')).strip()
        
        # Check for SEE NOTE
        if "SEE NOTE" in acc.upper() or "SEE NOTE" in acc1.upper():
            found_see_note.append(f"Client: {client_id}, Index: {idx}, Acc: '{acc}', Acc.1: '{acc1}'")
            
        # Check for targets
        for tid in target_ids:
            if tid in acc or tid in acc1:
                found_accounts.append(f"Client: {client_id}, Index: {idx}, Found {tid} in '{acc}'/'{acc1}'")

print("\n--- RESULTS ---")
print(f"Found {len(found_see_note)} instances of 'SEE NOTE'")
for note in found_see_note[:5]:
    print(note)

print(f"\nFound {len(found_accounts)} matches for target IDs")
for match in found_accounts:
    print(match)

if not found_accounts:
    print("WARNING: Target accounts NOT found in database.")

conn.close()
