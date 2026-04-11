"""Fix Chris's evaluations in the local DB - replace with correct 656 rows from fixed CSV."""
import sqlite3, json, csv, os
from datetime import datetime

FIXED_CSV = os.path.expanduser(r'~\Downloads\Chris_evaluations_fixed.csv')
DB_PATH = 'dashboard/dashboard.db'
CLIENT_ID = 'Chris'

# Read the fixed CSV
with open(FIXED_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fixed_rows = [dict(row) for row in reader]

print(f'Fixed CSV: {len(fixed_rows)} rows')

# Connect to DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get current data
cur.execute("SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,))
result = cur.fetchone()
if not result:
    print(f'ERROR: No client data found for {CLIENT_ID}')
    db.close()
    exit(1)

current_evals = json.loads(result[0]) if result[0] else []
print(f'Current DB: {len(current_evals)} evaluations')

# Replace evaluations with fixed CSV data
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id=?",
            (json.dumps(fixed_rows), CLIENT_ID))

# Get next version number
cur.execute("SELECT MAX(version) FROM data_history WHERE client_id=?", (CLIENT_ID,))
max_ver = cur.fetchone()[0] or 0
new_ver = max_ver + 1

# Record in data_history
cur.execute("""INSERT INTO data_history 
    (client_id, version, action, changed_by, changed_by_type, ip_address, change_source, change_description, evaluations, created_at)
    VALUES (?, ?, 'UPDATE', 'system_fix', 'super_admin', '127.0.0.1', 'dedup_fix', ?, ?, ?)""",
    (CLIENT_ID, new_ver,
     f'Deduplicated evaluations: {len(current_evals)} → {len(fixed_rows)} (removed {len(current_evals) - len(fixed_rows)} duplicate rows from repeated CSV imports)',
     json.dumps(fixed_rows),
     datetime.now().isoformat()))

db.commit()

# Verify
cur.execute("SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,))
verify = json.loads(cur.fetchone()[0])
print(f'After fix: {len(verify)} evaluations')
print(f'Removed: {len(current_evals) - len(verify)} duplicate rows')

db.close()
print('Done.')
