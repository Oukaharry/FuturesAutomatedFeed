"""
One-time DB cleanup: strip trailing spaces from user_credentials and sessions,
and remove duplicate user_credentials entries.

Run on server: python fix_whitespace_users.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "dashboard.db")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Find usernames with trailing/leading whitespace
cur.execute("SELECT id, username, email, user_type FROM user_credentials WHERE username != TRIM(username)")
dirty = cur.fetchall()
print(f"Found {len(dirty)} user_credentials rows with whitespace issues:")
for r in dirty:
    print(f"  id={r['id']} username='{r['username']}' type={r['user_type']}")

# 2. Delete whitespace duplicates (where a trimmed version already exists)
cur.execute("""
    DELETE FROM user_credentials
    WHERE username != TRIM(username)
      AND EXISTS (
          SELECT 1 FROM user_credentials AS uc2
          WHERE TRIM(user_credentials.username) = uc2.username
            AND user_credentials.user_type = uc2.user_type
      )
""")
print(f"  → Deleted {cur.rowcount} whitespace duplicate rows")

# 3. Trim any remaining (where no clean version exists yet)
cur.execute("UPDATE user_credentials SET username = TRIM(username) WHERE username != TRIM(username)")
print(f"  → Trimmed {cur.rowcount} rows")

# 4. Remove any other exact duplicates (keep lowest id)
cur.execute("""
    DELETE FROM user_credentials
    WHERE id NOT IN (
        SELECT MIN(id) FROM user_credentials GROUP BY username, user_type
    )
""")
print(f"  → Removed {cur.rowcount} remaining duplicate rows")

# 4. Fix sessions too
cur.execute("UPDATE sessions SET user_identifier = TRIM(user_identifier) WHERE user_identifier != TRIM(user_identifier)")
print(f"  → Trimmed {cur.rowcount} session rows")

conn.commit()
conn.close()
print("\nDone. Wayne should now be able to see his clients.")
