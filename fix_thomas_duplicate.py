"""
Fix: Delete duplicate user_credentials row for thomasandvpf@gmail.com

Problem: Two rows exist for the same email:
  id=41:  username='Thomas'          (old, wrong - login resolves here first)
  id=107: username='Thomas De Jager' (correct - matches clients_data)

This causes client login to redirect to /dashboard/Thomas which has no data.

Run on server:  python fix_thomas_duplicate.py
"""
import sqlite3
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

EMAIL = "thomasandvpf@gmail.com"
CORRECT_NAME = "Thomas De Jager"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print(f"Using DB: {DB_PATH}\n")

# 1. Show current state
cursor.execute("""
    SELECT id, username, email, user_type, is_active
    FROM user_credentials
    WHERE email = ?
    ORDER BY id
""", (EMAIL,))
rows = cursor.fetchall()

print(f"Current rows for {EMAIL}:")
for r in rows:
    marker = " ✅ KEEP" if r['username'] == CORRECT_NAME else " ❌ DELETE"
    print(f"  id={r['id']}: username='{r['username']}' type='{r['user_type']}' active={r['is_active']}{marker}")

if len(rows) <= 1:
    print("\nNo duplicates found. Nothing to do.")
    conn.close()
    sys.exit(0)

# 2. Delete all rows that don't match the correct name
ids_to_delete = [r['id'] for r in rows if r['username'] != CORRECT_NAME]
if not ids_to_delete:
    print("\nNo stale rows to delete.")
    conn.close()
    sys.exit(0)

print(f"\nDeleting {len(ids_to_delete)} stale row(s): ids {ids_to_delete}")
for row_id in ids_to_delete:
    cursor.execute("DELETE FROM user_credentials WHERE id = ?", (row_id,))
conn.commit()

# 3. Also clear any active sessions with the wrong username
cursor.execute("""
    DELETE FROM sessions
    WHERE user_type = 'client' AND user_identifier != ? 
    AND user_identifier IN ('Thomas')
""", (CORRECT_NAME,))
deleted_sessions = cursor.rowcount
conn.commit()
if deleted_sessions:
    print(f"Cleared {deleted_sessions} stale session(s) for 'Thomas'")

# 4. Verify
cursor.execute("""
    SELECT id, username, email, user_type, is_active
    FROM user_credentials
    WHERE email = ?
""", (EMAIL,))
remaining = cursor.fetchall()
print(f"\nAfter fix — rows for {EMAIL}:")
for r in remaining:
    print(f"  id={r['id']}: username='{r['username']}' type='{r['user_type']}' active={r['is_active']}")

if len(remaining) == 1 and remaining[0]['username'] == CORRECT_NAME:
    print("\n✅ Fixed! Thomas De Jager should now see data on login.")
    print("   Ask Thomas to clear cookies or log out and back in.")
else:
    print("\n⚠️  Unexpected state — please check manually.")

conn.close()
