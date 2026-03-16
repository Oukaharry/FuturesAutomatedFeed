"""
Diagnostic script: Mohit Gupta — data shows in admin view but empty in client view.
Same pattern as Thomas De Jager fix.

Run:  python diagnose_mohit.py
"""
import sqlite3
import json
import os
import sys

EMAIL = "mohitgupta@gmail.com"  # Will search for all Mohit variants
SEARCH_NAMES = ["Mohit Gupta", "Mohit", "mohit"]

# Auto-detect DB path
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

print(f"Using DB: {DB_PATH}")
print(f"DB size: {os.path.getsize(DB_PATH) / 1024:.0f} KB\n")
print("=" * 80)
print("DIAGNOSING CLIENT VIEW EMPTY FOR: Mohit Gupta")
print("=" * 80)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# ──── 1. HIERARCHY LOOKUP ────
print("\n─── 1. HIERARCHY LOOKUP ───")
hierarchy_path = os.path.join(os.path.dirname(DB_PATH), '..', 'config', 'Hierarchy.json')
if not os.path.exists(hierarchy_path):
    hierarchy_path = os.path.join(os.path.dirname(__file__), 'config', 'Hierarchy.json')

hierarchy_client_name = None
hierarchy_email = None
if os.path.exists(hierarchy_path):
    with open(hierarchy_path, 'r', encoding='utf-8') as f:
        hierarchy = json.load(f)
    for admin_name, admin_data in hierarchy.get("admins", {}).items():
        for trader_name, trader_data in admin_data.get("traders", {}).items():
            for client in trader_data.get("clients", []):
                cname = client.get("name", "")
                cemail = (client.get("email") or "").lower().strip()
                if "mohit" in cname.lower() or "gupta" in cname.lower():
                    hierarchy_client_name = cname
                    hierarchy_email = cemail
                    print(f"  Found in hierarchy: Admin={admin_name}, Trader={trader_name}")
                    print(f"  Client name (client_id): '{hierarchy_client_name}'")
                    print(f"  Email: '{hierarchy_email}'")
                    print(f"  Category: {client.get('category')}")
    if not hierarchy_client_name:
        print("  WARNING: Mohit NOT FOUND in Hierarchy.json!")
else:
    print(f"  WARNING: Hierarchy.json not found at {hierarchy_path}")

# ──── 2. USER_CREDENTIALS CHECK ────
print("\n─── 2. USER_CREDENTIALS TABLE ───")
cursor = conn.cursor()
cursor.execute("""
    SELECT id, username, email, user_type, parent_admin, parent_trader, is_active
    FROM user_credentials
    WHERE username LIKE '%mohit%' OR username LIKE '%Mohit%' 
       OR email LIKE '%mohit%' OR email LIKE '%gupta%'
""")
rows = cursor.fetchall()

db_username = None
db_email = None
db_row_id = None
if rows:
    for row in rows:
        r = dict(row)
        print(f"  Row: id={r['id']}, username='{r['username']}', email='{r['email']}', "
              f"user_type='{r['user_type']}', parent_admin='{r['parent_admin']}', "
              f"parent_trader='{r['parent_trader']}', is_active={r['is_active']}")
        if r['user_type'] == 'client' and r['is_active']:
            db_username = r['username']
            db_email = r['email']
            db_row_id = r['id']
else:
    print("  No rows found for 'mohit' or 'gupta'")

# ──── 3. KEY CHECK: Mismatch? ────
print("\n─── 3. USERNAME MISMATCH CHECK (LIKELY ROOT CAUSE) ───")
if db_username and hierarchy_client_name:
    if db_username == hierarchy_client_name:
        print(f"  ✅ MATCH: DB username '{db_username}' == hierarchy name '{hierarchy_client_name}'")
    else:
        print(f"  ❌ MISMATCH FOUND!")
        print(f"     DB user_credentials username: '{db_username}'")
        print(f"     Hierarchy.json client name:    '{hierarchy_client_name}'")
        print(f"")
        print(f"  Login resolves username='{db_username}' → session stores '{db_username}'")
        print(f"  → Redirects to /dashboard/{db_username}")
        print(f"  → Frontend requests /api/data?client_id={db_username}")
        print(f"  → get_client_data('{db_username}') returns NOTHING (data stored under '{hierarchy_client_name}')")
elif db_username:
    print(f"  DB username: '{db_username}' (no hierarchy name to compare)")
elif hierarchy_client_name:
    print(f"  No DB row found — login will fall back to hierarchy name '{hierarchy_client_name}'")
else:
    print("  Neither found!")

# ──── 4. CLIENTS_DATA TABLE ────
print("\n─── 4. CLIENTS_DATA TABLE ───")
for name in set(filter(None, [hierarchy_client_name, db_username])):
    cursor.execute("SELECT client_id, last_updated FROM clients_data WHERE client_id = ?", (name,))
    row = cursor.fetchone()
    if row:
        r = dict(row)
        print(f"  ✅ Data EXISTS for client_id='{r['client_id']}', last_updated={r['last_updated']}")
        cursor.execute("SELECT evaluations, statistics FROM clients_data WHERE client_id = ?", (name,))
        detail = cursor.fetchone()
        if detail:
            evals = json.loads(detail['evaluations'] or '[]')
            print(f"     Evaluations: {len(evals)} rows")
    else:
        print(f"  ❌ No data for client_id='{name}'")

# Also LIKE search
cursor.execute("SELECT client_id FROM clients_data WHERE client_id LIKE '%ohit%' OR client_id LIKE '%upta%'")
like_rows = cursor.fetchall()
if like_rows:
    print(f"\n  All client_ids containing 'ohit' or 'upta':")
    for r in like_rows:
        print(f"    - '{r['client_id']}'")

# ──── 5. SIMULATED LOGIN FLOW ────
print("\n─── 5. SIMULATED LOGIN FLOW ───")
login_email = hierarchy_email or db_email or "mohit's email"
print(f"  Step 1: User enters '{login_email}' on login page")

cursor.execute("""
    SELECT username, email, user_type, is_active
    FROM user_credentials
    WHERE (username = ? OR email = ?) AND is_active = 1
""", (login_email, login_email))
db_hit = cursor.fetchone()

if db_hit:
    db_hit = dict(db_hit)
    resolved = db_hit['username']
    print(f"  Step 2: find_user_by_identifier → FOUND in user_credentials")
    print(f"           username='{resolved}', user_type='{db_hit['user_type']}'")
else:
    print(f"  Step 2: find_user_by_identifier → NOT in user_credentials")
    print(f"  Step 3: Falls back to hierarchy → '{hierarchy_client_name}'")
    resolved = hierarchy_client_name

if resolved:
    print(f"  Step 4: create_session(user_type='client', user_identifier='{resolved}')")
    print(f"  Step 5: Redirect → /dashboard/{resolved}")
    print(f"  Step 6: Fetches /api/data?client_id={resolved}")

    cursor.execute("SELECT client_id FROM clients_data WHERE client_id = ?", (resolved,))
    has_data = cursor.fetchone()
    if has_data:
        print(f"  Step 7: get_client_data('{resolved}') → ✅ DATA FOUND")
    else:
        print(f"  Step 7: get_client_data('{resolved}') → ❌ NO DATA!")
        if hierarchy_client_name and resolved != hierarchy_client_name:
            print(f"           Data stored under '{hierarchy_client_name}' but login queries '{resolved}'")
            print(f"           → EMPTY DASHBOARD!")

# ──── FIX ────
print("\n" + "=" * 80)
if db_username and hierarchy_client_name and db_username != hierarchy_client_name:
    print("DIAGNOSIS: USERNAME MISMATCH between user_credentials and hierarchy.")
    print(f"  user_credentials.username = '{db_username}'")
    print(f"  hierarchy client name     = '{hierarchy_client_name}'")
    print(f"  Data stored under         = '{hierarchy_client_name}' (from push)")
    print(f"  Client login resolves to  = '{db_username}' (from user_credentials)")
    print()
    print("FIX:")
    print(f"  UPDATE user_credentials SET username='{hierarchy_client_name}' WHERE id={db_row_id};")
    print()
    
    apply = input("Apply fix now? (y/n): ").strip().lower()
    if apply == 'y':
        cursor.execute("UPDATE user_credentials SET username=? WHERE id=?", 
                       (hierarchy_client_name, db_row_id))
        conn.commit()
        print(f"\n  ✅ FIXED: username updated from '{db_username}' to '{hierarchy_client_name}'")
        print("  Client should now see their data on next login.")
    else:
        print("  Skipped. Run the SQL manually if needed.")
elif db_username and hierarchy_client_name and db_username == hierarchy_client_name:
    print("USERNAME MATCHES — issue is elsewhere.")
    print("Check if:")
    print("  1. clients_data has actual evaluations (not empty)")
    print("  2. The client email in Hierarchy.json matches exactly what they use to log in")
    print("  3. There are duplicate user_credentials rows causing confusion")
else:
    print("INCONCLUSIVE — see details above for next steps.")

conn.close()
