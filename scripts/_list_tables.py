import sqlite3
conn = sqlite3.connect('dashboard/dashboard.db')
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for r in rows:
    print(r[0])
