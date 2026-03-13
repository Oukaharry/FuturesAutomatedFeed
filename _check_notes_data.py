"""Quick check of notes data in local DB"""
import sqlite3

conn = sqlite3.connect('dashboard/dashboard.db')
cur = conn.cursor()

# Total notes
cur.execute('SELECT COUNT(*) FROM cell_notes')
print(f'Total notes: {cur.fetchone()[0]}')

# Prop Day notes
cur.execute("SELECT COUNT(*) FROM cell_notes WHERE column_key LIKE 'Prop Day%'")
print(f'Prop Day notes: {cur.fetchone()[0]}')

# Show all Prop Day notes
cur.execute("""
    SELECT client_id, row_index, column_key, note_content 
    FROM cell_notes 
    WHERE column_key LIKE 'Prop Day%' 
    ORDER BY client_id, row_index 
    LIMIT 30
""")
print('\nProp Day notes:')
for r in cur.fetchall():
    print(f'  client={r[0]}, row_idx={r[1]}, col={r[2]}, content="{r[3][:60]}"')

# Distinct clients with notes
cur.execute("SELECT DISTINCT client_id FROM cell_notes")
clients = [r[0] for r in cur.fetchall()]
print(f'\nClients with any notes: {clients}')

for cid in clients:
    cur.execute("SELECT COUNT(DISTINCT row_index) FROM cell_notes WHERE client_id=? AND column_key LIKE 'Prop Day%'", (cid,))
    cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cell_notes WHERE client_id=?", (cid,))
    total = cur.fetchone()[0]
    print(f'  {cid}: {cnt} rows with Prop Day notes, {total} total notes')

# Check the screenshot - this is dark theme = main dashboard, Chris Ream's data
# Let's see what client_id maps to Chris
cur.execute("SELECT DISTINCT client_id FROM cell_notes")
print(f'\nAll client_ids in cell_notes: {[r[0] for r in cur.fetchall()]}')

# Check if there's a mapping from client names
# Also check the row indices vs actual eval count
print('\n--- Row index range for Prop Day notes ---')
cur.execute("""
    SELECT client_id, MIN(row_index) as min_idx, MAX(row_index) as max_idx
    FROM cell_notes 
    WHERE column_key LIKE 'Prop Day%'
    GROUP BY client_id
""")
for r in cur.fetchall():
    print(f'  {r[0]}: row indices {r[1]} to {r[2]}')

conn.close()
