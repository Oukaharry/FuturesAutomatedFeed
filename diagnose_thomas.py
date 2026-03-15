"""
Diagnostic script: Why does thomasandvpf@gmail.com show data in admin view but empty in client view?

Run on the server:  python diagnose_thomas.py
"""
import sqlite3
import json
import os
import sys

EMAIL = "thomasandvpf@gmail.com"

# Auto-detect DB path (works from repo root or dashboard dir)
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
    print("ERROR: dashboard.db not found. Run this from the project root or dashboard/ dir.")
    sys.exit(1)

print(f"Using DB: {DB_PATH}")
print(f"DB size: {os.path.getsize(DB_PATH) / 1024:.0f} KB\n")
print("=" * 80)
print(f"DIAGNOSING CLIENT VIEW EMPTY FOR: {EMAIL}")
print("=" * 80)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# ──────────────────────────────────────────────────────────────
# 1. Check Hierarchy.json — what client_id does the push use?
# ──────────────────────────────────────────────────────────────
print("\n─── 1. HIERARCHY LOOKUP ───")
hierarchy_path = os.path.join(os.path.dirname(DB_PATH), '..', 'config', 'Hierarchy.json')
if not os.path.exists(hierarchy_path):
    hierarchy_path = os.path.join(os.path.dirname(__file__), 'config', 'Hierarchy.json')

hierarchy_client_name = None
if os.path.exists(hierarchy_path):
    with open(hierarchy_path, 'r', encoding='utf-8') as f:
        hierarchy = json.load(f)
    for admin_name, admin_data in hierarchy.get("admins", {}).items():
        for trader_name, trader_data in admin_data.get("traders", {}).items():
            for client in trader_data.get("clients", []):
                if client.get("email", "").lower().strip() == EMAIL.lower():
                    hierarchy_client_name = client["name"]
                    print(f"  Found in hierarchy: Admin={admin_name}, Trader={trader_name}")
                    print(f"  Client name (used as client_id): '{hierarchy_client_name}'")
                    print(f"  Email: {client.get('email')}")
                    print(f"  Category: {client.get('category')}")
    if not hierarchy_client_name:
        print(f"  WARNING: {EMAIL} NOT FOUND in Hierarchy.json!")
else:
    print(f"  WARNING: Hierarchy.json not found at {hierarchy_path}")

# ──────────────────────────────────────────────────────────────
# 2. Check user_credentials — what username does login resolve?
# ──────────────────────────────────────────────────────────────
print("\n─── 2. USER_CREDENTIALS TABLE ───")
cursor = conn.cursor()
cursor.execute("""
    SELECT id, username, email, user_type, parent_admin, parent_trader, is_active
    FROM user_credentials
    WHERE email = ? OR username = ?
""", (EMAIL, hierarchy_client_name or EMAIL))
rows = cursor.fetchall()

db_username = None
if rows:
    for row in rows:
        r = dict(row)
        print(f"  Row: id={r['id']}, username='{r['username']}', email='{r['email']}', "
              f"user_type='{r['user_type']}', parent_admin='{r['parent_admin']}', "
              f"parent_trader='{r['parent_trader']}', is_active={r['is_active']}")
        if r['user_type'] == 'client' and r['is_active']:
            db_username = r['username']
else:
    print(f"  No rows found for email={EMAIL} or username='{hierarchy_client_name}'")

# ──────────────────────────────────────────────────────────────
# 3. KEY CHECK: Does DB username match hierarchy client name?
# ──────────────────────────────────────────────────────────────
print("\n─── 3. USERNAME MISMATCH CHECK (LIKELY ROOT CAUSE) ───")
if db_username and hierarchy_client_name:
    if db_username == hierarchy_client_name:
        print(f"  ✅ MATCH: DB username '{db_username}' == hierarchy name '{hierarchy_client_name}'")
    else:
        print(f"  ❌ MISMATCH FOUND!")
        print(f"     DB user_credentials username: '{db_username}'")
        print(f"     Hierarchy.json client name:    '{hierarchy_client_name}'")
        print(f"")
        print(f"  This is the bug! unified_login checks user_credentials FIRST.")
        print(f"  Login resolves username='{db_username}' → session stores user_identifier='{db_username}'")
        print(f"  → Redirects to /dashboard/{db_username}")
        print(f"  → Frontend requests /api/data?client_id={db_username}")
        print(f"  → get_client_data('{db_username}') returns NOTHING (data stored under '{hierarchy_client_name}')")
        print(f"")
        print(f"  FIX: Update user_credentials username to match hierarchy:")
        print(f"    UPDATE user_credentials SET username='{hierarchy_client_name}' WHERE id=<id>;")
elif db_username:
    print(f"  DB username: '{db_username}' (no hierarchy name to compare)")
elif hierarchy_client_name:
    print(f"  No DB row found — login will fall back to hierarchy name '{hierarchy_client_name}'")
    print(f"  This path should work. Issue may be elsewhere.")
else:
    print(f"  Neither found!")

# ──────────────────────────────────────────────────────────────
# 4. Check clients_data table — what client_ids have data?
# ──────────────────────────────────────────────────────────────
print("\n─── 4. CLIENTS_DATA TABLE ───")
# Check by exact hierarchy name
for name in set(filter(None, [hierarchy_client_name, db_username])):
    cursor.execute("SELECT client_id, last_updated FROM clients_data WHERE client_id = ?", (name,))
    row = cursor.fetchone()
    if row:
        r = dict(row)
        print(f"  ✅ Data EXISTS for client_id='{r['client_id']}', last_updated={r['last_updated']}")
        # Peek at evaluations count
        cursor.execute("SELECT evaluations, statistics, identity FROM clients_data WHERE client_id = ?", (name,))
        detail = cursor.fetchone()
        if detail:
            evals = json.loads(detail['evaluations'] or '[]')
            stats = json.loads(detail['statistics'] or '{}')
            identity = json.loads(detail['identity'] or '{}')
            print(f"     Evaluations: {len(evals)} rows")
            print(f"     Identity email: {identity.get('email', 'N/A')}")
            print(f"     Identity sheet_url: {identity.get('sheet_url', 'N/A')[:60] if identity.get('sheet_url') else 'N/A'}")
            hr = stats.get('hedging_review', {})
            if hr:
                print(f"     Hedging Review: deposits=${hr.get('total_deposits', 0):.2f}, "
                      f"balance=${hr.get('current_balance', 0):.2f}")
    else:
        print(f"  ❌ No data for client_id='{name}'")

# Also search by LIKE for partial matches
cursor.execute("SELECT client_id FROM clients_data WHERE client_id LIKE ?", (f"%Thomas%",))
like_rows = cursor.fetchall()
if like_rows:
    print(f"\n  All client_ids containing 'Thomas':")
    for r in like_rows:
        print(f"    - '{r['client_id']}'")

# ──────────────────────────────────────────────────────────────
# 5. Check active sessions for this user
# ──────────────────────────────────────────────────────────────
print("\n─── 5. ACTIVE SESSIONS ───")
try:
    cursor.execute("""
        SELECT session_token, user_type, user_identifier, created_at, expires_at, ip_address
        FROM sessions
        WHERE user_identifier LIKE ?
        ORDER BY created_at DESC LIMIT 10
    """, (f"%Thomas%",))
    sessions = cursor.fetchall()
    if sessions:
        for s in sessions:
            s = dict(s)
            token_prefix = s['session_token'][:12] + '...'
            expired = ' (EXPIRED)' if s.get('expires_at', '') < '2026' else ''
            print(f"  Token={token_prefix} user_type='{s['user_type']}', "
                  f"user_identifier='{s['user_identifier']}', "
                  f"created={s['created_at']}, expires={s['expires_at']}{expired}, ip={s['ip_address']}")
    else:
        print("  No sessions found for 'Thomas*'")
except Exception as e:
    print(f"  (sessions table query failed: {e})")
    # Try listing columns
    try:
        cursor.execute("PRAGMA table_info(sessions)")
        cols = [r['name'] for r in cursor.fetchall()]
        print(f"  Sessions table columns: {cols}")
    except:
        pass

# ──────────────────────────────────────────────────────────────
# 6. Check audit log for recent logins
# ──────────────────────────────────────────────────────────────
print("\n─── 6. RECENT LOGIN AUDIT ───")
try:
    cursor.execute("""
        SELECT action, user_type, user_identifier, details, timestamp
        FROM audit_log
        WHERE (user_identifier LIKE ? OR details LIKE ?)
        AND action LIKE '%LOGIN%'
        ORDER BY timestamp DESC LIMIT 10
    """, (f"%Thomas%", f"%thomas%"))
    logs = cursor.fetchall()
    if logs:
        for log in logs:
            l = dict(log)
            print(f"  {l['timestamp']} | {l['action']} | type={l['user_type']} | "
                  f"user='{l['user_identifier']}' | {l.get('details', '')}")
    else:
        print("  No login audit entries found for 'Thomas*'")
except Exception as e:
    print(f"  (audit_log query failed: {e})")

# ──────────────────────────────────────────────────────────────
# 7. Simulate the login flow
# ──────────────────────────────────────────────────────────────
print("\n─── 7. SIMULATED LOGIN FLOW ───")
print(f"  Step 1: User enters '{EMAIL}' on login page")

# find_user_by_identifier searches by username OR email
cursor.execute("""
    SELECT username, email, user_type, is_active
    FROM user_credentials
    WHERE (username = ? OR email = ?) AND is_active = 1
""", (EMAIL, EMAIL))
db_hit = cursor.fetchone()

if db_hit:
    db_hit = dict(db_hit)
    resolved = db_hit['username']
    print(f"  Step 2: find_user_by_identifier → FOUND in user_credentials")
    print(f"           username='{resolved}', user_type='{db_hit['user_type']}'")
    print(f"  Step 3: Skips hierarchy lookup (DB takes priority)")
else:
    print(f"  Step 2: find_user_by_identifier → NOT in user_credentials")
    print(f"  Step 3: Falls back to get_user_by_email → hierarchy name = '{hierarchy_client_name}'")
    resolved = hierarchy_client_name

print(f"  Step 4: create_session(user_type='client', user_identifier='{resolved}')")
print(f"  Step 5: Redirect → /dashboard/{resolved}")
print(f"  Step 6: Frontend sets CLIENT_ID = '{resolved}'")
print(f"  Step 7: Fetches /api/data?client_id={resolved}")

# Check if data exists under that resolved name
cursor.execute("SELECT client_id FROM clients_data WHERE client_id = ?", (resolved,))
has_data = cursor.fetchone()
if has_data:
    print(f"  Step 8: get_client_data('{resolved}') → ✅ DATA FOUND")
else:
    print(f"  Step 8: get_client_data('{resolved}') → ❌ NO DATA!")
    if hierarchy_client_name and resolved != hierarchy_client_name:
        print(f"           Data is stored under '{hierarchy_client_name}' but client view queries '{resolved}'")
        print(f"           → EMPTY DASHBOARD for the client!")

print("\n" + "=" * 80)
if db_hit and hierarchy_client_name and db_hit['username'] != hierarchy_client_name:
    print("DIAGNOSIS: USERNAME MISMATCH between user_credentials and hierarchy.")
    print(f"  user_credentials.username = '{db_hit['username']}'")
    print(f"  hierarchy client name     = '{hierarchy_client_name}'")
    print(f"  Data is stored under      = '{hierarchy_client_name}' (from push)")
    print(f"  Client login resolves to  = '{db_hit['username']}' (from user_credentials)")
    print()
    print("FIX OPTIONS:")
    print(f"  Option A: Update DB username to match hierarchy:")
    print(f"    UPDATE user_credentials SET username='{hierarchy_client_name}' WHERE id={rows[0]['id']};")
    print(f"  Option B: Delete the stale DB row (login will use hierarchy):")
    print(f"    DELETE FROM user_credentials WHERE id={rows[0]['id']};")
else:
    print("DIAGNOSIS: No obvious username mismatch detected.")
    print("Other possibilities:")
    print("  - Session cookie from old login still active with wrong user_identifier")
    print("  - Client clearing cookies and re-logging may fix it")
    print("  - Check browser devtools: Network tab → /api/data response")

# ──────────────────────────────────────────────────────────────
# 8. EVALUATIONS ACTIVE FILTER CHECK
# ──────────────────────────────────────────────────────────────
print("\n─── 8. EVALUATIONS ACTIVE FILTER CHECK ───")
print("  (Active Only hides: failed, breached, deleted, closed, completed)")
data_name = hierarchy_client_name or db_username
if data_name:
    cursor.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (data_name,))
    row = cursor.fetchone()
    if row:
        evals = json.loads(row['evaluations'] or '[]')
        FAIL_WORDS = ['fail', 'breach', 'delete', 'closed', 'sl']
        FUNDED_HIDE = ['fail', 'breach', 'delete', 'closed', 'sl', 'complete']
        
        active_count = 0
        filtered_count = 0
        for i, ev in enumerate(evals):
            status_p1 = str(ev.get('Status P1', '')).lower()
            status_funded = str(ev.get('Status', '')).lower()
            is_deleted = ev.get('_deleted', False)
            
            hidden = False
            reason = ''
            if is_deleted:
                hidden = True
                reason = '_deleted=True'
            elif any(w in status_p1 for w in FAIL_WORDS):
                hidden = True
                reason = f"Status P1='{ev.get('Status P1', '')}'"
            elif any(w in status_funded for w in FUNDED_HIDE):
                hidden = True
                reason = f"Status='{ev.get('Status', '')}'"
            
            if hidden:
                filtered_count += 1
                if filtered_count <= 5:
                    print(f"  Row {i+1}: HIDDEN ({reason}) - {ev.get('Prop Firm', '?')} {ev.get('Account Size', '?')}")
            else:
                active_count += 1
        
        if filtered_count > 5:
            print(f"  ... and {filtered_count - 5} more hidden rows")
        
        print(f"\n  Total: {len(evals)} evaluations, {active_count} active, {filtered_count} filtered out")
        if active_count == 0:
            print(f"  ❌ ALL evaluations filtered out by Active Only! This would show empty table.")
            print(f"     But admin also has Active Only checked and sees data, so this alone isn't the cause.")
        elif active_count > 0:
            print(f"  ✅ {active_count} rows should be visible with Active Only enabled")

# ──────────────────────────────────────────────────────────────
# 9. CHECK FOR MULTIPLE CLIENTS WITH SIMILAR NAMES
# ──────────────────────────────────────────────────────────────
print("\n─── 9. ALL CLIENTS IN DB ───")
cursor.execute("SELECT client_id, last_updated FROM clients_data ORDER BY last_updated DESC")
all_clients = cursor.fetchall()
print(f"  Total clients in DB: {len(all_clients)}")
for c in all_clients[:30]:
    marker = " <<<" if 'thomas' in c['client_id'].lower() else ""
    print(f"    '{c['client_id']}' (updated: {c['last_updated']}){marker}")

# ──────────────────────────────────────────────────────────────
# 10. Check user_credentials for ALL clients (look for duplicate/conflicting entries)
# ──────────────────────────────────────────────────────────────
print("\n─── 10. ALL USER_CREDENTIALS (client type) ───")
cursor.execute("""
    SELECT id, username, email, user_type, is_active 
    FROM user_credentials 
    WHERE user_type = 'client'
    ORDER BY username
""")
all_creds = cursor.fetchall()
print(f"  Total client credentials: {len(all_creds)}")
for c in all_creds:
    marker = " <<<" if 'thomas' in c['username'].lower() or (c['email'] and 'thomas' in c['email'].lower()) else ""
    print(f"    id={c['id']}: '{c['username']}' email='{c['email']}' active={c['is_active']}{marker}")

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
conn.close()
