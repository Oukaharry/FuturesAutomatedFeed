"""
One-time sync: copy category from hierarchy.json into each client's DB identity blob.
This fixes the inconsistency where Edit Client modal wrote only to hierarchy.json
but financial overview reads from the DB identity.
"""
import json
import os
import sqlite3

HIERARCHY_FILE = os.path.join(os.path.dirname(__file__), 'config', 'hierarchy.json')
DB_PATH = os.path.join(os.path.dirname(__file__), 'dashboard', 'dashboard.db')


def main():
    with open(HIERARCHY_FILE, 'r') as f:
        hierarchy = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    updated = 0
    skipped = 0

    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            for client in trader_data.get('clients', []):
                client_name = client.get('name', '')
                hierarchy_cat = (client.get('category') or '').strip()

                if not client_name:
                    continue

                # Read current DB identity
                cursor.execute("SELECT identity FROM clients_data WHERE client_id = ?", (client_name,))
                row = cursor.fetchone()
                if not row:
                    print(f"  SKIP (not in DB): {client_name}")
                    skipped += 1
                    continue

                identity = json.loads(row[0]) if row[0] else {}
                db_profile = (identity.get('profile') or identity.get('category') or '').strip()

                # Determine the canonical category
                # Hierarchy is authoritative; default to 'Private' if empty
                canonical = hierarchy_cat if hierarchy_cat else 'Private'

                if db_profile.upper() == canonical.upper():
                    # Already in sync
                    continue

                # Update DB identity
                identity['profile'] = canonical
                identity['category'] = canonical
                cursor.execute("UPDATE clients_data SET identity = ? WHERE client_id = ?",
                               (json.dumps(identity), client_name))
                updated += 1
                print(f"  SYNCED: {client_name}: DB was '{db_profile}' -> now '{canonical}' (hierarchy: '{hierarchy_cat}')")

    conn.commit()
    conn.close()
    print(f"\nDone. {updated} clients synced, {skipped} not in DB.")


if __name__ == '__main__':
    main()
