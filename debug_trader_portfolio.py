"""
Debug script: Why is a trader's portfolio empty?
Usage: python debug_trader_portfolio.py <email_or_name>

Examples:
  python debug_trader_portfolio.py otienookok19@gmail.com
  python debug_trader_portfolio.py "Steve Okok"
"""
import json
import sqlite3
import os
import sys

if len(sys.argv) < 2:
    print("Usage: python debug_trader_portfolio.py <email_or_name>")
    sys.exit(1)

SEARCH = sys.argv[1].strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dashboard", "dashboard.db")
HIERARCHY_PATH = os.path.join(BASE_DIR, "config", "hierarchy.json")

print("=" * 70)
print(f"DEBUG: Trader Portfolio for '{SEARCH}'")
print("=" * 70)

# ── 1. Hierarchy lookup ──
print("\n[1] HIERARCHY.JSON - Traders matching search")
print("-" * 50)
with open(HIERARCHY_PATH, "r") as f:
    hierarchy = json.load(f)

search_lower = SEARCH.lower()
matches = []
for admin_name, admin_data in hierarchy.get("admins", {}).items():
    for trader_name, trader_data in admin_data.get("traders", {}).items():
        t_email = trader_data.get("email", "").lower()
        if search_lower in trader_name.lower() or search_lower == t_email:
            clients = trader_data.get("clients", [])
            matches.append({
                "admin": admin_name,
                "trader_key": trader_name,
                "email": trader_data.get("email", ""),
                "clients": [c.get("name", "?") for c in clients],
            })

if matches:
    for m in matches:
        print(f"  Admin: {m['admin']}")
        print(f"  Trader key: '{m['trader_key']}'")
        print(f"  Email: '{m['email']}'")
        print(f"  Clients ({len(m['clients'])}): {m['clients']}")
        print()
else:
    print(f"  NOT FOUND in hierarchy.json!")

# ── 2. user_credentials ──
print("\n[2] USER_CREDENTIALS TABLE")
print("-" * 50)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
    SELECT id, username, email, user_type, is_active 
    FROM user_credentials 
    WHERE username LIKE ? OR email LIKE ?
""", (f"%{SEARCH}%", f"%{SEARCH}%"))
rows = cur.fetchall()
if rows:
    for row in rows:
        trail = " ← HAS TRAILING SPACE!" if row['username'] != row['username'].strip() else ""
        print(f"  id={row['id']} username='{row['username']}' email='{row['email']}' type={row['user_type']} active={row['is_active']}{trail}")
else:
    print(f"  No matches found")

# ── 3. Sessions ──
print("\n[3] RECENT SESSIONS")
print("-" * 50)
cur.execute("""
    SELECT user_type, user_identifier, created_at, expires_at
    FROM sessions 
    WHERE user_identifier LIKE ?
    ORDER BY created_at DESC LIMIT 5
""", (f"%{SEARCH}%",))
sessions = cur.fetchall()
if sessions:
    for s in sessions:
        trail = " ← HAS TRAILING SPACE!" if s['user_identifier'] != s['user_identifier'].strip() else ""
        print(f"  identifier='{s['user_identifier']}' type={s['user_type']} created={s['created_at']}{trail}")
else:
    # Also try broader search
    broader = SEARCH.split()[0] if ' ' in SEARCH else SEARCH.split('@')[0]
    cur.execute("""
        SELECT user_type, user_identifier, created_at
        FROM sessions 
        WHERE user_identifier LIKE ?
        ORDER BY created_at DESC LIMIT 5
    """, (f"%{broader}%",))
    sessions = cur.fetchall()
    if sessions:
        print(f"  (Broadened search to '{broader}')")
        for s in sessions:
            print(f"  identifier='{s['user_identifier']}' type={s['user_type']} created={s['created_at']}")
    else:
        print(f"  No sessions found")

# ── 4. Simulate login ──
print("\n[4] SIMULATED LOGIN")
print("-" * 50)

# Try email lookup
test_email = SEARCH if '@' in SEARCH else None
if not test_email:
    # Try to find email from user_credentials or hierarchy
    for row in rows:
        if row['email']:
            test_email = row['email']
            break
    if not test_email:
        for m in matches:
            if m['email']:
                test_email = m['email']
                break

if test_email:
    print(f"  Login email: {test_email}")
    
    # Step A: DB lookup
    cur.execute("SELECT username, user_type FROM user_credentials WHERE email = ? AND is_active = 1", (test_email,))
    db_user = cur.fetchone()
    if db_user:
        print(f"  DB lookup → username='{db_user['username']}', type={db_user['user_type']}")
        login_username = db_user['username']
    else:
        print(f"  DB lookup → NOT FOUND")
        login_username = None
    
    # Step B: Hierarchy lookup (fallback)
    sys.path.insert(0, BASE_DIR)
    from config.hierarchy import get_user_by_email
    hier_user = get_user_by_email(test_email)
    if hier_user:
        print(f"  Hierarchy lookup → username='{hier_user['username']}', type={hier_user['user_type']}")
        if not login_username:
            login_username = hier_user['username']
    else:
        print(f"  Hierarchy lookup → NOT FOUND")
    
    if login_username:
        login_username_stripped = login_username.strip()
        print(f"\n  Session would store: '{login_username}'")
        print(f"  After .strip(): '{login_username_stripped}'")
        print(f"  Redirect: /trader/{login_username_stripped}")
        
        # Step C: Hierarchy key match
        print(f"\n  Checking get_filtered_hierarchy('trader', '{login_username_stripped}'):")
        found = False
        for admin_name, admin_data in hierarchy.get("admins", {}).items():
            traders = admin_data.get("traders", {})
            if login_username_stripped in traders:
                clients = traders[login_username_stripped].get("clients", [])
                print(f"    ✅ MATCH: '{login_username_stripped}' found under admin '{admin_name}'")
                print(f"    Clients: {[c.get('name') for c in clients]}")
                found = True
                break
        
        if not found:
            print(f"    ❌ '{login_username_stripped}' NOT found as trader key!")
            print(f"\n    Hierarchy trader keys containing similar names:")
            for admin_name, admin_data in hierarchy.get("admins", {}).items():
                for tname in admin_data.get("traders", {}).keys():
                    if any(w.lower() in tname.lower() for w in login_username_stripped.split()):
                        print(f"      - '{tname}' (admin: {admin_name})")
            
            print(f"\n    ⚠️  ROOT CAUSE: The username from login ('{login_username_stripped}') does not")
            print(f"       match any trader key in hierarchy.json!")
            print(f"       FIX: Either rename the trader in hierarchy.json, or update user_credentials.")
else:
    print(f"  Could not determine email for login simulation")

conn.close()
print("\n" + "=" * 70)
print("Done.")
