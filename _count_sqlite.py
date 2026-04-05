"""Count rows in each SQLite table."""
import sqlite3, os
db = os.path.join('dashboard', 'dashboard.db')
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM [{t}]')
    count = cur.fetchone()[0]
    print(f'  {t:30s} {count:>8,} rows')
conn.close()
