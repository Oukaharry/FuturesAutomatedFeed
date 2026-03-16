"""
Diagnose & Fix: Client data visible in admin view but not client view.

Root cause: The client's `username` in user_credentials doesn't match
the `client_id` key in clients_data. When admin browses to the client,
the URL uses the correct clients_data key. When the client logs in,
the URL uses their user_credentials username — which may differ.

Usage:
  python fix_client_view.py                    # Scan ALL clients for mismatches
  python fix_client_view.py "Mohit Gupta"      # Diagnose + fix specific client
"""
import sqlite3
import json
import os
import sys

CANDIDATES = [
    os.path.join(os.path.dirname(__file__), 'dashboard', 'dashboard.db'),
    os.path.join(os.path.dirname(__file__), 'dashboard.db'),
]
DB_PATH = None
for p in CANDIDATES:
    if os.path.exists(p):
        DB_PATH = p
        break

if not DB_PATH:
    print("ERROR: dashboard.db not found.")
    sys.exit(1)

HIERARCHY_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), 'dashboard', 'hierarchy.json'),
    os.path.join(os.path.dirname(__file__), 'hierarchy.json'),
]
HIERARCHY = {}
for p in HIERARCHY_CANDIDATES:
    if os.path.exists(p):
        with open(p) as f:
            HIERARCHY = json.load(f)
        break

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print(f"Using DB: {DB_PATH}")
print(f"Hierarchy loaded: {bool(HIERARCHY)}\n")

TARGET = sys.argv[1].strip() if len(sys.argv) > 1 else None


def get_all_hierarchy_clients():
    """Extract all client names and emails from hierarchy.json."""
    clients = []
    for admin_name, admin_data in HIERARCHY.get('admins', {}).items():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            for client in trader_data.get('clients', []):
                clients.append({
                    'name': client.get('name', ''),
                    'email': client.get('email', ''),
                    'admin': admin_name,
                    'trader': trader_name,
                })
    return clients


def diagnose_client(name):
    """Full diagnosis for a single client name."""
    cursor = conn.cursor()
    print(f"{'='*80}")
    print(f"  DIAGNOSING: {name}")
    print(f"{'='*80}")

    # 1. Check clients_data
    cursor.execute("SELECT client_id FROM clients_data WHERE client_id = ?", (name,))
    cd_row = cursor.fetchone()
    print(f"\n  [clients_data] client_id='{name}': {'FOUND' if cd_row else 'NOT FOUND'}")

    # 2. Check user_credentials
    cursor.execute("""
        SELECT id, username, email, user_type, is_active
        FROM user_credentials
        WHERE username = ? OR email LIKE ?
        ORDER BY id
    """, (name, f'%{name.split()[0].lower() if name else ""}%'))
    cred_rows = cursor.fetchall()
    print(f"\n  [user_credentials] matching rows:")
    if not cred_rows:
        print(f"    (none found)")
    for r in cred_rows:
        print(f"    id={r['id']}: username='{r['username']}' email='{r['email']}' "
              f"type='{r['user_type']}' active={r['is_active']}")

    # 3. Search clients_data by fuzzy match (what the admin might be seeing)
    cursor.execute("SELECT client_id FROM clients_data")
    all_cids = [r['client_id'] for r in cursor.fetchall()]
    fuzzy = [cid for cid in all_cids if name.lower() in cid.lower() or
             (name.split()[0].lower() in cid.lower() if name else False)]
    if fuzzy and not cd_row:
        print(f"\n  [clients_data] fuzzy matches:")
        for cid in fuzzy:
            print(f"    -> '{cid}'")

    # 4. Check hierarchy
    h_clients = get_all_hierarchy_clients()
    h_match = [c for c in h_clients if c['name'] == name or
               name.lower() in c['name'].lower()]
    print(f"\n  [hierarchy.json] matching entries:")
    if not h_match:
        print(f"    (none found)")
    for c in h_match:
        print(f"    name='{c['name']}' email='{c['email']}' "
              f"admin='{c['admin']}' trader='{c['trader']}'")

    # 5. Identify the problem
    print(f"\n  DIAGNOSIS:")

    # Find what credential email maps to
    client_creds = [r for r in cred_rows if r['user_type'] == 'client']

    if not client_creds:
        print(f"    No client credential found for '{name}'.")
        print(f"    -> Client cannot log in at all.")
        return

    # Check for duplicates
    if len(client_creds) > 1:
        emails = set(r['email'] for r in client_creds)
        for email in emails:
            dupes = [r for r in client_creds if r['email'] == email]
            if len(dupes) > 1:
                print(f"    DUPLICATE credentials for email '{email}':")
                for r in dupes:
                    has_data = bool(cursor.execute(
                        "SELECT 1 FROM clients_data WHERE client_id = ?",
                        (r['username'],)).fetchone())
                    marker = " <- HAS DATA" if has_data else " <- NO DATA"
                    print(f"      id={r['id']}: username='{r['username']}'{marker}")

    # Check username vs client_id mismatch
    for cred in client_creds:
        uname = cred['username']
        has_data = bool(cursor.execute(
            "SELECT 1 FROM clients_data WHERE client_id = ?",
            (uname,)).fetchone())
        if has_data:
            print(f"    username='{uname}' -> /dashboard/{uname} -> HAS DATA. OK.")
        else:
            print(f"    username='{uname}' -> /dashboard/{uname} -> NO DATA!")
            # Find what client_id the data is actually under
            if fuzzy:
                print(f"    -> Data likely stored under: {fuzzy}")
                print(f"    -> FIX NEEDED: username '{uname}' should be '{fuzzy[0]}'")

    return client_creds, fuzzy


def scan_all():
    """Scan all client credentials and find mismatches."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, user_type, is_active
        FROM user_credentials
        WHERE user_type = 'client'
        ORDER BY username
    """)
    all_creds = cursor.fetchall()

    # Get all client_ids from clients_data
    cursor.execute("SELECT client_id FROM clients_data")
    all_data_ids = set(r['client_id'] for r in cursor.fetchall())

    mismatches = []
    duplicates = {}

    # Check for username -> client_id mismatches
    for cred in all_creds:
        if cred['username'] not in all_data_ids:
            mismatches.append(cred)

    # Check for duplicate emails
    email_groups = {}
    for cred in all_creds:
        email = (cred['email'] or '').lower()
        if email:
            email_groups.setdefault(email, []).append(cred)
    duplicates = {e: rows for e, rows in email_groups.items() if len(rows) > 1}

    print(f"{'='*80}")
    print(f"  FULL SCAN: {len(all_creds)} client credentials, {len(all_data_ids)} client data records")
    print(f"{'='*80}")

    if mismatches:
        print(f"\n  MISMATCHES ({len(mismatches)} clients login -> no data):")
        print(f"  {'Username':<30} {'Email':<40} {'Possible data key'}")
        print(f"  {'-'*100}")
        for cred in mismatches:
            # Try to find the actual data key
            first = cred['username'].split()[0].lower() if cred['username'] else ''
            possible = [cid for cid in all_data_ids if first and first in cid.lower()]
            print(f"  {cred['username']:<30} {cred['email'] or '':<40} {possible[:3]}")
    else:
        print(f"\n  No mismatches found. All client usernames have matching data.")

    if duplicates:
        print(f"\n  DUPLICATE EMAILS ({len(duplicates)} emails with multiple credentials):")
        for email, rows in duplicates.items():
            print(f"\n  Email: {email}")
            for r in rows:
                has_data = r['username'] in all_data_ids
                marker = "HAS DATA" if has_data else "NO DATA"
                print(f"    id={r['id']}: username='{r['username']}' [{marker}]")

    return mismatches, duplicates


def fix_client(name):
    """Fix a specific client's username mismatch."""
    cursor = conn.cursor()
    result = diagnose_client(name)
    if not result:
        return

    client_creds, fuzzy = result

    if not fuzzy:
        print(f"\n  Cannot auto-fix: no fuzzy match found in clients_data.")
        print(f"  Check manually what client_id the admin uses to view this client.")
        return

    # Find the credential that has no data
    for cred in client_creds:
        has_data = bool(cursor.execute(
            "SELECT 1 FROM clients_data WHERE client_id = ?",
            (cred['username'],)).fetchone())

        if not has_data and fuzzy:
            correct_name = fuzzy[0]
            old_name = cred['username']

            print(f"\n  FIX: Rename username '{old_name}' -> '{correct_name}' (id={cred['id']})")
            confirm = input(f"  Apply fix? (yes/no): ").strip().lower()

            if confirm == 'yes':
                # Check if correct_name already has a credential
                cursor.execute(
                    "SELECT id FROM user_credentials WHERE username = ? AND user_type = 'client'",
                    (correct_name,))
                existing = cursor.fetchone()

                if existing:
                    # Delete the wrong one instead
                    print(f"  Credential for '{correct_name}' already exists (id={existing['id']}).")
                    print(f"  Deleting stale credential id={cred['id']} (username='{old_name}')")
                    cursor.execute("DELETE FROM user_credentials WHERE id = ?", (cred['id'],))
                else:
                    # Rename
                    cursor.execute(
                        "UPDATE user_credentials SET username = ? WHERE id = ?",
                        (correct_name, cred['id']))

                # Clear stale sessions
                cursor.execute(
                    "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
                    (old_name,))
                stale = cursor.rowcount

                conn.commit()
                print(f"  Applied. Cleared {stale} stale session(s).")
                print(f"  Client should log out and back in.")

                # Verify
                cursor.execute(
                    "SELECT id, username, email FROM user_credentials "
                    "WHERE username = ? AND user_type = 'client'",
                    (correct_name,))
                check = cursor.fetchone()
                if check:
                    has_data = bool(cursor.execute(
                        "SELECT 1 FROM clients_data WHERE client_id = ?",
                        (correct_name,)).fetchone())
                    print(f"\n  VERIFY: username='{check['username']}' -> data={'YES' if has_data else 'NO'}")
                    if has_data:
                        print(f"  FIX SUCCESSFUL")
                    else:
                        print(f"  WARNING: Still no data. Check clients_data manually.")
            else:
                print(f"  Skipped.")


if __name__ == '__main__':
    if TARGET:
        fix_client(TARGET)
    else:
        scan_all()

    conn.close()
