import sqlite3
conn = sqlite3.connect('dashboard/dashboard.db')
rows = conn.execute("SELECT column_key, note_content FROM cell_notes WHERE column_key LIKE 'Prop Day%' LIMIT 30").fetchall()
for col, content in rows:
    print(f"{col}: {repr(content)}")
