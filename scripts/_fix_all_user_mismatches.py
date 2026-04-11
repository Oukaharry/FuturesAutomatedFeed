"""
Fix ALL user_credentials ↔ hierarchy.json mismatches.
Finds users whose username or user_type doesn't match their hierarchy entry,
and corrects them. Also removes duplicates.

Run from project root:  python _fix_all_user_mismatches.py
Add --dry-run to preview without making changes.
"""
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRY_RUN = '--dry-run' in sys.argv

from dashboard.database import get_connection
from config.hierarchy import load_hierarchy

print("=" * 70)
print(f"FIX ALL USER ↔ HIERARCHY MISMATCHES {'(DRY RUN)' if DRY_RUN else ''}")
print("=" * 70)

# ── 1. Build lookup from hierarchy.json ──
hierarchy = load_hierarchy()
admins = hierarchy.get('admins', {})

# email → (correct_name, correct_type)
hierarchy_by_email = {}
# name_lower → (correct_name, correct_type)
hierarchy_by_name = {}

for admin_name, admin_data in admins.items():
    admin_email = (admin_data.get('email') or '').strip().lower()
    if admin_email:
        hierarchy_by_email[admin_email] = (admin_name, 'admin')
    hierarchy_by_name[admin_name.strip().lower()] = (admin_name, 'admin')

    for trader_name, trader_data in admin_data.get('traders', {}).items():
        trader_email = (trader_data.get('email') or '').strip().lower()
        if trader_email:
            hierarchy_by_email[trader_email] = (trader_name, 'trader')
        hierarchy_by_name[trader_name.strip().lower()] = (trader_name, 'trader')

        for client in trader_data.get('clients', []):
            client_name = client.get('name', '')
            client_email = (client.get('email') or '').strip().lower()
            if client_email:
                hierarchy_by_email[client_email] = (client_name, 'client')
            if client_name:
                hierarchy_by_name[client_name.strip().lower()] = (client_name, 'client')

# ── 2. Check all user_credentials ──
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, user_type, is_active
        FROM user_credentials
        ORDER BY id
    """)
    all_users = [dict(row) for row in cursor.fetchall()]

print(f"\nTotal users in DB: {len(all_users)}")
print(f"Total hierarchy entries: {len(hierarchy_by_email)} by email, {len(hierarchy_by_name)} by name\n")

fixes = []
duplicates_to_delete = []

# Group by email to detect duplicates
from collections import defaultdict
by_email = defaultdict(list)
for u in all_users:
    email = (u['email'] or '').strip().lower()
    if email:
        by_email[email].append(u)

# Check for duplicates first
for email, users in by_email.items():
    if len(users) > 1:
        # Find the "correct" one (matching hierarchy name, or higher ID = newer)
        correct = None
        for u in users:
            match = hierarchy_by_email.get(email) or hierarchy_by_name.get(u['username'].strip().lower())
            if match and u['username'].strip().lower() == match[0].strip().lower() and u['user_type'] == match[1]:
                correct = u
                break
        if not correct:
            # Pick the one with highest ID (most recently created)
            correct = max(users, key=lambda x: x['id'])
        
        for u in users:
            if u['id'] != correct['id']:
                duplicates_to_delete.append(u)
                print(f"  🗑️  DUPLICATE: id={u['id']} username='{u['username']}' type='{u['user_type']}' email='{u['email']}'")
                print(f"        → Keeping id={correct['id']} username='{correct['username']}' type='{correct['user_type']}'")

# Now check remaining users for mismatches
ids_to_delete = {d['id'] for d in duplicates_to_delete}

for u in all_users:
    if u['id'] in ids_to_delete:
        continue
    
    email = (u['email'] or '').strip().lower()
    name_lower = u['username'].strip().lower()
    
    # Try to find match in hierarchy by email first, then by name
    match = hierarchy_by_email.get(email)
    if not match:
        match = hierarchy_by_name.get(name_lower)
    if not match:
        # Try partial match — user's first name might match start of hierarchy name
        for hier_name_lower, hier_info in hierarchy_by_name.items():
            if hier_name_lower.startswith(name_lower) or name_lower.startswith(hier_name_lower):
                match = hier_info
                break
    
    if not match:
        continue  # Not in hierarchy at all (super_admin, etc.)
    
    correct_name, correct_type = match
    
    needs_fix = False
    reasons = []
    
    if u['user_type'] != correct_type:
        reasons.append(f"user_type: '{u['user_type']}' → '{correct_type}'")
        needs_fix = True
    
    if u['username'] != correct_name:
        reasons.append(f"username: '{u['username']}' → '{correct_name}'")
        needs_fix = True
    
    if needs_fix:
        fixes.append((u, correct_name, correct_type))
        print(f"\n  ❌ MISMATCH: id={u['id']} email='{u['email']}'")
        for r in reasons:
            print(f"     • {r}")

# ── 3. Summary ──
print(f"\n{'=' * 70}")
print(f"SUMMARY: {len(duplicates_to_delete)} duplicates to remove, {len(fixes)} mismatches to fix")
print(f"{'=' * 70}")

if not duplicates_to_delete and not fixes:
    print("  ✅ Everything looks correct!")
    sys.exit(0)

if DRY_RUN:
    print("\n  (DRY RUN — no changes made. Remove --dry-run to apply.)")
    sys.exit(0)

# ── 4. Apply fixes ──
with get_connection() as conn:
    cursor = conn.cursor()
    
    # Delete duplicates
    for d in duplicates_to_delete:
        cursor.execute("DELETE FROM user_credentials WHERE id = ?", (d['id'],))
        print(f"  🗑️  Deleted duplicate id={d['id']} ('{d['username']}', '{d['user_type']}')")
    
    # Fix mismatches
    for u, correct_name, correct_type in fixes:
        try:
            cursor.execute("""
                UPDATE user_credentials
                SET username = ?, user_type = ?
                WHERE id = ?
            """, (correct_name, correct_type, u['id']))
            print(f"  ✅ Fixed id={u['id']}: '{u['username']}' ({u['user_type']}) → '{correct_name}' ({correct_type})")
        except Exception as e:
            print(f"  ⚠️  Could not fix id={u['id']}: {e}")
            # If UNIQUE conflict, the correct record already exists — just delete this one
            if 'UNIQUE' in str(e):
                cursor.execute("DELETE FROM user_credentials WHERE id = ?", (u['id'],))
                print(f"     → Deleted conflicting record id={u['id']} instead")
    
    # Clear all sessions for affected users to force fresh login
    affected_names = set()
    for d in duplicates_to_delete:
        affected_names.add(d['username'])
    for u, cn, ct in fixes:
        affected_names.add(u['username'])
        affected_names.add(cn)
    
    try:
        for name in affected_names:
            cursor.execute("DELETE FROM sessions WHERE user_identifier = ?", (name,))
        print(f"\n  🗑️  Cleared sessions for {len(affected_names)} affected users")
    except Exception:
        pass  # sessions table might not have expected schema
    
    conn.commit()

# ── 5. Verify ──
print(f"\n{'=' * 70}")
print("VERIFICATION:")
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, user_type FROM user_credentials
        WHERE user_type IN ('admin', 'trader')
        ORDER BY user_type, username
    """)
    for row in cursor.fetchall():
        r = dict(row)
        print(f"  [{r['user_type']:6s}] {r['username']:25s} {r['email']}")

print("=" * 70)
print("Done. Reload the web app for changes to take effect.")
