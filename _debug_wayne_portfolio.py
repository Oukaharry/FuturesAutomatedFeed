"""
Debug script: Why is Wayne Ogolla's trader portfolio empty?

Run from server: python _debug_wayne_portfolio.py
"""
import json
import sqlite3
import os
import sys

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dashboard", "dashboard.db")
HIERARCHY_PATH = os.path.join(BASE_DIR, "config", "hierarchy.json")

print("=" * 70)
print("DEBUG: Wayne Ogolla Portfolio - Why Is It Empty?")
print("=" * 70)

# ── 1. Check hierarchy.json ──
print("\n[1] HIERARCHY.JSON ANALYSIS")
print("-" * 50)
with open(HIERARCHY_PATH, "r") as f:
    hierarchy = json.load(f)

wayne_found = []
for admin_name, admin_data in hierarchy.get("admins", {}).items():
    traders = admin_data.get("traders", {})
    for trader_name, trader_data in traders.items():
        if "wayne" in trader_name.lower():
            clients = trader_data.get("clients", [])
            wayne_found.append({
                "admin": admin_name,
                "trader_key": trader_name,
                "email": trader_data.get("email", ""),
                "num_clients": len(clients),
                "client_names": [c.get("name", "?") for c in clients],
            })

if wayne_found:
    for w in wayne_found:
        print(f"  Admin: {w['admin']}")
        print(f"  Trader key: '{w['trader_key']}'")
        print(f"  Email: '{w['email']}'")
        print(f"  Clients ({w['num_clients']}): {w['client_names']}")
        print()
else:
    print("  ❌ NO trader with 'Wayne' in name found in hierarchy.json!")

# ── 2. Check user_credentials table ──
print("\n[2] USER_CREDENTIALS TABLE")
print("-" * 50)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT * FROM user_credentials WHERE username LIKE '%wayne%' OR username LIKE '%ogolla%' OR email LIKE '%wayne%' OR email LIKE '%ogolla%'")
rows = cur.fetchall()
if rows:
    for row in rows:
        print(f"  username: '{row['username']}'")
        print(f"  email: '{row['email']}'")
        print(f"  user_type: '{row['user_type']}'")
        print(f"  is_active: {row['is_active']}")
        print()
else:
    print("  ❌ No 'wayne' or 'ogolla' entries in user_credentials")

# ── 3. Check active sessions for Wayne ──
print("\n[3] ACTIVE SESSIONS")
print("-" * 50)
try:
    cur.execute("SELECT * FROM sessions WHERE user_identifier LIKE '%wayne%' OR user_identifier LIKE '%ogolla%' ORDER BY created_at DESC LIMIT 5")
    sessions = cur.fetchall()
    if sessions:
        for s in sessions:
            print(f"  user_type: '{s['user_type']}', identifier: '{s['user_identifier']}'")
            print(f"  created: {s['created_at']}, expires: {s['expires_at']}")
            print()
    else:
        print("  No sessions found for Wayne")
except Exception as e:
    print(f"  Error checking sessions: {e}")

# ── 4. Check what clients exist in DB with Wayne as trader ──
print("\n[4] DB CLIENTS WITH WAYNE AS TRADER (identity column)")
print("-" * 50)
cur.execute("SELECT client_id, identity FROM clients_data")
wayne_clients_db = []
for row in cur.fetchall():
    identity = row["identity"]
    if identity:
        try:
            ident = json.loads(identity) if isinstance(identity, str) else identity
            trader = ident.get("trader", "")
            if "wayne" in str(trader).lower() or "ogolla" in str(trader).lower():
                wayne_clients_db.append({
                    "client_id": row["client_id"],
                    "trader": trader,
                    "admin": ident.get("admin", ""),
                })
        except (json.JSONDecodeError, AttributeError):
            pass

if wayne_clients_db:
    print(f"  Found {len(wayne_clients_db)} clients in DB with Wayne as trader:")
    for c in wayne_clients_db:
        print(f"    - {c['client_id']} (admin: {c['admin']}, trader: {c['trader']})")
else:
    print("  ❌ No clients in DB have Wayne as their trader")

# ── 5. Simulate login flow ──
print("\n[5] SIMULATED LOGIN FLOW")
print("-" * 50)
# When Wayne logs in with ogollawayne@gmail.com:
# 1. find_user_by_identifier looks up email in user_credentials
# 2. If not found, get_user_by_email checks hierarchy.json
# 3. Returns username which becomes user_identifier in session
# 4. /trader/<username> route uses that username
# 5. Frontend fetches /api/hierarchy which calls get_filtered_hierarchy(trader, username)
# 6. get_filtered_hierarchy searches hierarchy.json for trader_name match

test_email = "ogollawayne@gmail.com"
print(f"  Testing login with: {test_email}")

# Check DB first
cur.execute("SELECT * FROM user_credentials WHERE email = ?", (test_email,))
db_user = cur.fetchone()
if db_user:
    print(f"  DB lookup → username='{db_user['username']}', type='{db_user['user_type']}'")
    login_username = db_user['username']
else:
    print(f"  DB lookup → NOT FOUND")
    # Fall through to hierarchy lookup
    login_username = None

# Check hierarchy
sys.path.insert(0, BASE_DIR)
from config.hierarchy import get_user_by_email
hier_user = get_user_by_email(test_email)
if hier_user:
    print(f"  Hierarchy lookup → username='{hier_user['username']}', type='{hier_user['user_type']}'")
    if not login_username:
        login_username = hier_user['username']
else:
    print(f"  Hierarchy lookup → NOT FOUND")

if login_username:
    print(f"\n  Login would use username: '{login_username}'")
    print(f"  Redirect would be: /trader/{login_username}")
    
    # Simulate get_filtered_hierarchy for this trader
    print(f"\n  Simulating get_filtered_hierarchy('trader', '{login_username}'):")
    found_in_hierarchy = False
    for admin_name, admin_data in hierarchy.get("admins", {}).items():
        traders = admin_data.get("traders", {})
        if login_username in traders:
            trader_data = traders[login_username]
            clients = trader_data.get("clients", [])
            print(f"    ✅ Found under admin '{admin_name}'")
            print(f"    Clients returned: {[c.get('name') for c in clients]}")
            found_in_hierarchy = True
            break
    
    if not found_in_hierarchy:
        print(f"    ❌ '{login_username}' NOT found as a trader key in hierarchy.json!")
        print(f"    This is WHY the portfolio is empty!")
        print(f"\n    The hierarchy.json has these trader keys:")
        for admin_name, admin_data in hierarchy.get("admins", {}).items():
            for tname in admin_data.get("traders", {}).keys():
                if "wayne" in tname.lower():
                    print(f"      - '{tname}' (under admin '{admin_name}')")
else:
    print(f"\n  ❌ Login would FAIL - email not found anywhere")

# ── 6. Root cause summary ──
print("\n" + "=" * 70)
print("ROOT CAUSE ANALYSIS")
print("=" * 70)
print("""
The issue is a MISMATCH between:

1. user_credentials table / login: Wayne logs in → session stores his username
2. hierarchy.json: The trader KEY used to look up clients

When the trader dashboard loads:
  - Frontend calls GET /api/hierarchy
  - Backend runs get_filtered_hierarchy('trader', <username from session>)
  - This searches hierarchy.json for a trader KEY matching the username
  - If the key doesn't match exactly → returns empty → "No Clients Assigned"

Check above output to see the exact mismatch.
""")

conn.close()
print("Done.")
