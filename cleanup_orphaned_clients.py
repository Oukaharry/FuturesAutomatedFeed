"""
Cleanup script: Delete clients from the database that have no admin/trader in the hierarchy.
Run server-side: python cleanup_orphaned_clients.py
"""
import os, sys, json, sqlite3

# Paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'dashboard', 'dashboard.db')
# Prefer the hierarchy file chosen by config.hierarchy (may point to restructured JSON)
HIERARCHY_PATH = os.path.join(SCRIPT_DIR, 'config', 'hierarchy.json')
try:
    from config import hierarchy as _hier
    HIERARCHY_PATH = getattr(_hier, 'HIERARCHY_FILE', HIERARCHY_PATH)
except Exception:
    pass

# Load hierarchy
if not os.path.exists(HIERARCHY_PATH):
    print(f"ERROR: Hierarchy file not found at {HIERARCHY_PATH}")
    sys.exit(1)

with open(HIERARCHY_PATH, 'r') as f:
    hierarchy = json.load(f)

# Build set of all client names in the hierarchy
hierarchy_clients = set()
for admin_name, admin_data in hierarchy.get('admins', {}).items():
    for trader_name, trader_data in admin_data.get('traders', {}).items():
        for client in trader_data.get('clients', []):
            name = client.get('name')
            if name:
                hierarchy_clients.add(name)

print(f"Hierarchy has {len(hierarchy_clients)} clients:")
for c in sorted(hierarchy_clients):
    print(f"  - {c}")

# Get all clients from database
if not os.path.exists(DB_PATH):
    print(f"\nERROR: Database not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute('SELECT client_id FROM clients_data')
db_clients = [row['client_id'] for row in cursor.fetchall()]

print(f"\nDatabase has {len(db_clients)} clients:")
for c in sorted(db_clients):
    print(f"  - {c}")

# Find orphans (in DB but not in hierarchy)
orphans = [c for c in db_clients if c not in hierarchy_clients]

if not orphans:
    print("\nNo orphaned clients found. Nothing to delete.")
    conn.close()
    sys.exit(0)

print(f"\n{'='*60}")
print(f"ORPHANED CLIENTS (in DB but not in hierarchy): {len(orphans)}")
print(f"{'='*60}")
for c in orphans:
    print(f"  - {c}")

# Confirm before deleting
print(f"\nThese {len(orphans)} client(s) will be PERMANENTLY deleted from:")
print("  - clients_data")
print("  - data_history")
print("  - cell_notes")
print("  - daily_watermarks")
print("  - waterlog_periods")

confirm = input("\nType DELETE to confirm: ").strip()
if confirm != "DELETE":
    print("Aborted.")
    conn.close()
    sys.exit(0)

# Delete orphaned clients
tables = ['clients_data', 'data_history', 'cell_notes', 'daily_watermarks', 'waterlog_periods']
for client_id in orphans:
    for table in tables:
        try:
            cursor.execute(f'DELETE FROM {table} WHERE client_id = ?', (client_id,))
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"  Deleted {deleted} row(s) from {table} for '{client_id}'")
        except Exception as e:
            print(f"  Warning: {table} for '{client_id}': {e}")

conn.commit()
conn.close()

print(f"\nDone. Deleted {len(orphans)} orphaned client(s) from the database.")
