"""
Fix Steve Okok: rename 'Stephen Okok' → 'Steve Okok' in user_credentials
and remove stale 'Steve' entry.

Run on server: python fix_steve_okok.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "dashboard.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Delete stale 'Steve' entry (id=30)
cur.execute("DELETE FROM user_credentials WHERE username = 'Steve' AND email LIKE '%okok%'")
print(f"Deleted 'Steve' entry: {cur.rowcount} row(s)")

# 2. Rename 'Stephen Okok' → 'Steve Okok' to match hierarchy.json
cur.execute("UPDATE user_credentials SET username = 'Steve Okok' WHERE username = 'Stephen Okok' AND email LIKE '%okok%'")
print(f"Renamed 'Stephen Okok' → 'Steve Okok': {cur.rowcount} row(s)")

# 3. Also fix any existing sessions
cur.execute("UPDATE sessions SET user_identifier = 'Steve Okok' WHERE user_identifier IN ('Stephen Okok', 'Steve')")
print(f"Fixed sessions: {cur.rowcount} row(s)")

conn.commit()
conn.close()
print("\nDone. Steve Okok should now see his 7 clients.")
