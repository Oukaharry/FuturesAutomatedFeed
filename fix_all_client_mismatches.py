"""
Batch fix: 20 client username mismatches found by fix_client_view.py scan.

Fixes:
  - 5 duplicate credentials → delete the stale one
  - 12 username typos → rename to match clients_data key
  - 3 no-data clients → skip (no clients_data record to match)

Run on server:  python fix_all_client_mismatches.py
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

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print(f"Using DB: {DB_PATH}\n")

# ═══════════════════════════════════════════════════════════════
# 1. DELETE DUPLICATE CREDENTIALS (stale row, correct one exists)
# ═══════════════════════════════════════════════════════════════
DUPLICATES_TO_DELETE = [
    # (id_to_delete, stale_username, correct_username_that_exists)
    (33, 'Alexander Estradar', 'Alexander Estrada'),
    (5,  'Corner Jogensen',    'Conner'),
    (65, 'Jiang Sheng Zhou',   'Jian Sheng Zhou'),
    (34, 'Kresha Wood',        'Kresha Turner'),
    (15, 'Lea Gallan',         'Lea Galan'),
]

# ═══════════════════════════════════════════════════════════════
# 2. RENAME CREDENTIALS (typo in username → correct clients_data key)
# ═══════════════════════════════════════════════════════════════
RENAMES = [
    # (old_username, new_username)
    ('Adam Weing',        'Adam Wenig'),
    ('Adrian Vasquez',    'Adrian Vazquez'),
    ('Amber',             'Amber Wood'),
    ('Brian SHore',       'Brian Shore'),
    ('Fall Back',         'Fallback'),
    ('Nitin Malhotra',    'Nitin'),
    ('Pierre Alexander',  'Pierre Alexandre'),
    ('Riaz Ahmed',        'Riaz'),
    ('Skyler',            'Skyler Colvin'),
]

# Leanghour has TWO stale credentials with different email typos.
# Rename one, delete the other (both map to 'Leanghour').
LEANGHOUR_RENAME = ('Leanghour Sorn', 'sornlsjojo@gmail.com', 'Leanghour')
LEANGHOUR_DELETE = ('Leanghour sorn', 'sornldsjojo@gmail.com')

# ═══════════════════════════════════════════════════════════════
# 3. NO-DATA CLIENTS (skip — no clients_data record to map to)
# ═══════════════════════════════════════════════════════════════
SKIP = [
    ('Changleam Eang',    'changlimeang@gmail.com',         'No clients_data match'),
    ('Fransisco Morales', 'pipcandletrader@gmail.com',      'No clients_data match'),
    ('Ian Hullinger',     'vpfianh@gmail.com',              'No clients_data match (fuzzy hits are false positives)'),
    ('Nikii',             'nvandervleuten@yahoo.com',       'No clients_data match'),
]


def verify_data_exists(client_id):
    cursor.execute("SELECT 1 FROM clients_data WHERE client_id = ?", (client_id,))
    return cursor.fetchone() is not None


def verify_cred_exists(username):
    cursor.execute(
        "SELECT id, username, email FROM user_credentials WHERE username = ? AND user_type = 'client'",
        (username,))
    return cursor.fetchone()


# ─── PRE-FLIGHT CHECKS ───
print("=" * 80)
print("  PRE-FLIGHT CHECKS")
print("=" * 80)
errors = 0

for row_id, stale, correct in DUPLICATES_TO_DELETE:
    cred = verify_cred_exists(correct)
    data = verify_data_exists(correct)
    status = "OK" if cred and data else "WARN"
    if not cred:
        print(f"  {status}: Correct credential '{correct}' NOT FOUND - skip delete of '{stale}'")
        errors += 1
    elif not data:
        print(f"  {status}: No clients_data for '{correct}' - delete of '{stale}' still valid")
    else:
        print(f"  OK: '{correct}' has credential + data. Safe to delete '{stale}' (id={row_id})")

for old, new in RENAMES:
    data = verify_data_exists(new)
    existing = verify_cred_exists(new)
    if existing:
        print(f"  WARN: '{new}' already has a credential (id={existing['id']}). Will DELETE '{old}' instead of rename.")
    elif not data:
        print(f"  WARN: No clients_data for '{new}'. Rename '{old}' anyway (data may come later).")
    else:
        print(f"  OK: '{new}' has data, no existing credential. Safe to rename '{old}'")

print()

if errors > 0:
    print(f"  {errors} error(s) found. Review above before proceeding.")

confirm = input("\nApply ALL fixes? (yes/no): ").strip().lower()
if confirm != 'yes':
    print("Aborted.")
    conn.close()
    sys.exit(0)

# ─── APPLY FIXES ───
print("\n" + "=" * 80)
print("  APPLYING FIXES")
print("=" * 80)

fixed = 0
skipped = 0

# 1. Delete duplicates
print("\n  --- Deleting duplicate credentials ---")
for row_id, stale, correct in DUPLICATES_TO_DELETE:
    cred = verify_cred_exists(correct)
    if not cred:
        print(f"  SKIP: '{correct}' credential missing, not safe to delete '{stale}'")
        skipped += 1
        continue
    cursor.execute("DELETE FROM user_credentials WHERE id = ?", (row_id,))
    cursor.execute(
        "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
        (stale,))
    sessions_cleared = cursor.rowcount
    print(f"  DELETED id={row_id} '{stale}' (keeping '{correct}')"
          f"{f', cleared {sessions_cleared} session(s)' if sessions_cleared else ''}")
    fixed += 1

# 2. Rename typos
print("\n  --- Renaming username typos ---")
for old, new in RENAMES:
    existing = verify_cred_exists(new)
    if existing:
        # Correct credential already exists → just delete the typo
        cursor.execute(
            "DELETE FROM user_credentials WHERE username = ? AND user_type = 'client'",
            (old,))
        cursor.execute(
            "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
            (old,))
        print(f"  DELETED '{old}' ('{new}' already has credential id={existing['id']})")
    else:
        cursor.execute(
            "UPDATE user_credentials SET username = ? WHERE username = ? AND user_type = 'client'",
            (new, old))
        if cursor.rowcount:
            cursor.execute(
                "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
                (old,))
            print(f"  RENAMED '{old}' -> '{new}'")
        else:
            print(f"  SKIP: '{old}' not found in user_credentials")
            skipped += 1
            continue
    fixed += 1

# 3. Leanghour special case (two stale creds → one data key)
print("\n  --- Leanghour (2 stale creds -> 1 data key) ---")
existing_lh = verify_cred_exists('Leanghour')
if existing_lh:
    # Already has correct credential, delete both stale ones
    for name in ('Leanghour Sorn', 'Leanghour sorn'):
        cursor.execute(
            "DELETE FROM user_credentials WHERE username = ? AND user_type = 'client'",
            (name,))
        if cursor.rowcount:
            print(f"  DELETED '{name}' ('{LEANGHOUR_RENAME[2]}' already has credential)")
            fixed += 1
        cursor.execute(
            "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
            (name,))
else:
    # Rename the first one, delete the second
    rename_name, rename_email, target = LEANGHOUR_RENAME
    cursor.execute(
        "UPDATE user_credentials SET username = ? WHERE username = ? AND user_type = 'client'",
        (target, rename_name))
    if cursor.rowcount:
        print(f"  RENAMED '{rename_name}' -> '{target}'")
        fixed += 1
    else:
        print(f"  SKIP: '{rename_name}' not found")
        skipped += 1

    del_name, del_email = LEANGHOUR_DELETE
    cursor.execute(
        "DELETE FROM user_credentials WHERE username = ? AND user_type = 'client'",
        (del_name,))
    if cursor.rowcount:
        print(f"  DELETED '{del_name}' (duplicate)")
        fixed += 1
    cursor.execute(
        "DELETE FROM sessions WHERE user_identifier = ? AND user_type = 'client'",
        (del_name,))

# 4. Report skipped
print("\n  --- Skipped (no clients_data) ---")
for name, email, reason in SKIP:
    print(f"  SKIP: '{name}' ({email}) - {reason}")

conn.commit()

# ─── VERIFICATION ───
print("\n" + "=" * 80)
print("  VERIFICATION")
print("=" * 80)

# Re-scan for mismatches
cursor.execute("""
    SELECT username FROM user_credentials
    WHERE user_type = 'client'
    ORDER BY username
""")
all_creds = [r['username'] for r in cursor.fetchall()]

cursor.execute("SELECT client_id FROM clients_data")
all_data = set(r['client_id'] for r in cursor.fetchall())

remaining_mismatches = [u for u in all_creds if u not in all_data]
print(f"\n  Total credentials: {len(all_creds)}")
print(f"  Total data records: {len(all_data)}")
print(f"  Fixed: {fixed}")
print(f"  Skipped: {skipped}")
print(f"  Remaining mismatches: {len(remaining_mismatches)}")

if remaining_mismatches:
    print(f"\n  Still mismatched (no clients_data):")
    for u in remaining_mismatches:
        print(f"    - '{u}'")

# Check for remaining duplicates
cursor.execute("""
    SELECT email, COUNT(*) as cnt FROM user_credentials
    WHERE user_type = 'client' AND email != ''
    GROUP BY LOWER(email) HAVING cnt > 1
""")
dup_emails = cursor.fetchall()
if dup_emails:
    print(f"\n  Remaining duplicate emails:")
    for r in dup_emails:
        print(f"    - {r['email']} ({r['cnt']} credentials)")
else:
    print(f"\n  No duplicate emails remaining.")

print(f"\n{'='*80}")
if remaining_mismatches:
    print(f"  DONE. {len(remaining_mismatches)} clients still have no data (need data push).")
else:
    print(f"  ALL CLEAR. Every client credential maps to existing data.")
print(f"  Affected clients should log out and back in.")
print(f"{'='*80}")

conn.close()
