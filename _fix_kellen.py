"""
Fix script: Correct Kellen's user_type and username so her portal works.
Run from the project root: python _fix_kellen.py

This script:
1. Reads hierarchy.json to find Kellen's correct role (admin) and name
2. Updates user_credentials to match: user_type='admin', username='Kellen Njeri'
3. Invalidates stale sessions so she gets a fresh login
"""
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_connection
from config.hierarchy import load_hierarchy

print("=" * 70)
print("FIX: Correcting Kellen's user_credentials")
print("=" * 70)

# ── 1. Determine correct name and role from hierarchy ──
hierarchy = load_hierarchy()
admins = hierarchy.get('admins', {})

correct_name = None
correct_type = None

for admin_name in admins:
    if 'kellen' in admin_name.lower():
        correct_name = admin_name
        correct_type = 'admin'
        break

if not correct_name:
    # Check as trader
    for admin_name, admin_data in admins.items():
        for trader_name in admin_data.get('traders', {}):
            if 'kellen' in trader_name.lower():
                correct_name = trader_name
                correct_type = 'trader'
                break
        if correct_name:
            break

if not correct_name:
    print("❌ Kellen not found anywhere in hierarchy.json — cannot fix.")
    sys.exit(1)

print(f"  Hierarchy role: {correct_type}")
print(f"  Hierarchy name: '{correct_name}'")

# ── 2. Find her current DB record ──
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, user_type
        FROM user_credentials
        WHERE LOWER(username) LIKE '%kellen%' OR LOWER(email) LIKE '%kellen%'
    """)
    rows = cursor.fetchall()

if not rows:
    print("❌ No user_credentials record found for Kellen — cannot fix.")
    sys.exit(1)

for row in rows:
    r = dict(row)
    print(f"\n  Current DB record:")
    print(f"    ID:        {r['id']}")
    print(f"    Username:  '{r['username']}'")
    print(f"    Email:     '{r['email']}'")
    print(f"    User Type: '{r['user_type']}'")

    changes = []
    if r['user_type'] != correct_type:
        changes.append(f"user_type: '{r['user_type']}' → '{correct_type}'")
    if r['username'].strip().lower() != correct_name.strip().lower():
        changes.append(f"username: '{r['username']}' → '{correct_name}'")

    if not changes:
        print(f"\n  ✅ Already correct — no changes needed.")
        continue

    print(f"\n  🔧 Applying fixes:")
    for c in changes:
        print(f"    • {c}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_credentials
            SET user_type = ?, username = ?
            WHERE id = ?
        """, (correct_type, correct_name, r['id']))
        conn.commit()
        print(f"  ✅ Updated user_credentials (id={r['id']})")

    # ── 3. Invalidate stale sessions so Kellen gets a fresh login ──
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                DELETE FROM sessions
                WHERE LOWER(user_identifier) LIKE '%kellen%'
            """)
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                print(f"  🗑️  Cleared {deleted} old session(s) — Kellen will need to log in again")
        except Exception as e:
            print(f"  ⚠️  Could not clear sessions: {e}")

# ── 4. Verify ──
print("\n" + "=" * 70)
print("VERIFICATION:")
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, email, user_type
        FROM user_credentials
        WHERE LOWER(username) LIKE '%kellen%' OR LOWER(email) LIKE '%kellen%'
    """)
    for row in cursor.fetchall():
        r = dict(row)
        print(f"  Username: '{r['username']}', Type: '{r['user_type']}', Email: '{r['email']}'")

print(f"\n  After fix, Kellen should:")
print(f"    1. Log in with her email (njerikellen01@gmail.com)")
print(f"    2. Be redirected to /admin/{correct_name}")
print(f"    3. See her trader (Gideon Oruma) and all clients")
print("=" * 70)
print("Done.")
