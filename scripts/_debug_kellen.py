"""
Debug script: Investigate why Kellen sees "No Clients Assigned"
Run from the project root: python _debug_kellen.py
"""
import sys, os, json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_connection
from config.hierarchy import load_hierarchy

print("=" * 70)
print("DEBUG: Kellen Portfolio Investigation")
print("=" * 70)

# ── 1. Check user_credentials for any Kellen-related entry ──
print("\n📋 1. Searching user_credentials for 'kellen'...")
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, user_type, parent_admin, parent_trader,
               is_active, must_change_password, last_login
        FROM user_credentials
        WHERE LOWER(username) LIKE '%kellen%' OR LOWER(email) LIKE '%kellen%'
    """)
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            r = dict(row)
            print(f"  ID:            {r['id']}")
            print(f"  Username:      {r['username']}")
            print(f"  Email:         {r['email']}")
            print(f"  User Type:     {r['user_type']}  ← THIS IS THE LOGIN ROLE")
            print(f"  Parent Admin:  {r['parent_admin']}")
            print(f"  Parent Trader: {r['parent_trader']}")
            print(f"  Active:        {r['is_active']}")
            print(f"  Last Login:    {r['last_login']}")
            print()
    else:
        print("  ❌ No user_credentials rows found matching 'kellen'")

# ── 2. Check hierarchy.json ──
print("\n📋 2. Checking hierarchy.json...")
hierarchy = load_hierarchy()
admins = hierarchy.get('admins', {})

kellen_as_admin = None
kellen_as_trader = None

for admin_name, admin_data in admins.items():
    if 'kellen' in admin_name.lower():
        kellen_as_admin = (admin_name, admin_data)
        print(f"  ✅ Found as ADMIN: '{admin_name}'")
        print(f"     Email: {admin_data.get('email', '(none)')}")
        traders = admin_data.get('traders', {})
        print(f"     Traders under admin: {list(traders.keys())}")
        for tname, tdata in traders.items():
            clients = tdata.get('clients', [])
            print(f"       Trader '{tname}': {len(clients)} clients → {[c.get('name') for c in clients]}")

    for trader_name, trader_data in admin_data.get('traders', {}).items():
        if 'kellen' in trader_name.lower():
            kellen_as_trader = (admin_name, trader_name, trader_data)
            print(f"  ✅ Found as TRADER: '{trader_name}' under admin '{admin_name}'")
            clients = trader_data.get('clients', [])
            print(f"     Clients: {[c.get('name') for c in clients]}")

if not kellen_as_admin and not kellen_as_trader:
    print("  ❌ 'Kellen' not found in hierarchy.json at all!")

# ── 3. Diagnose the mismatch ──
print("\n" + "=" * 70)
print("🔍 DIAGNOSIS")
print("=" * 70)

if rows:
    user = dict(rows[0])
    db_type = user['user_type']
    db_username = user['username']

    if kellen_as_admin:
        hier_admin_name = kellen_as_admin[0]
        if db_type != 'admin':
            print(f"\n  ❌ MISMATCH FOUND!")
            print(f"     hierarchy.json: Kellen is an ADMIN (key='{hier_admin_name}')")
            print(f"     user_credentials: user_type='{db_type}' (should be 'admin')")
            print(f"     → Login redirects to /trader/{db_username} instead of /admin/{db_username}")
            print(f"     → Trader lookup in hierarchy finds nothing → 'No Clients Assigned'")
        if db_username.strip().lower() != hier_admin_name.strip().lower():
            print(f"\n  ❌ NAME MISMATCH!")
            print(f"     hierarchy.json admin key: '{hier_admin_name}'")
            print(f"     user_credentials username: '{db_username}'")
            print(f"     → Even with correct user_type, the hierarchy lookup would fail")
        else:
            if db_type == 'admin':
                print(f"\n  ✅ Everything looks correct — type=admin, name matches hierarchy")
    elif kellen_as_trader:
        hier_trader_name = kellen_as_trader[1]
        if db_type != 'trader':
            print(f"\n  ❌ MISMATCH: hierarchy says TRADER but DB says '{db_type}'")
        if db_username.strip().lower() != hier_trader_name.strip().lower():
            print(f"\n  ❌ NAME MISMATCH!")
            print(f"     hierarchy.json trader key: '{hier_trader_name}'")
            print(f"     user_credentials username: '{db_username}'")
    else:
        print(f"\n  ❌ User exists in DB but not found in hierarchy.json at all!")
        print(f"     DB username: '{db_username}', type: '{db_type}'")
else:
    print("\n  ❌ No user found in database matching 'kellen'")

# ── 4. Show all available sessions for reference ──
print("\n\n📋 3. Active sessions matching 'kellen'...")
with get_connection() as conn:
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT token, user_type, user_identifier, created_at, expires_at
            FROM sessions
            WHERE LOWER(user_identifier) LIKE '%kellen%'
            ORDER BY created_at DESC LIMIT 5
        """)
        sessions = cursor.fetchall()
        if sessions:
            for s in sessions:
                s = dict(s)
                print(f"  Session: type={s['user_type']}, identifier='{s['user_identifier']}', created={s['created_at']}")
        else:
            print("  No active sessions found")
    except Exception as e:
        print(f"  Could not query sessions: {e}")

print("\n" + "=" * 70)
print("Done.")
