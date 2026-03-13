import sqlite3

conn = sqlite3.connect('dashboard/dashboard.db')
cur = conn.cursor()

cur.execute(
    "SELECT client_id, row_index, column_key, note_content, created_by, updated_at "
    "FROM cell_notes "
    "WHERE column_key LIKE 'Prop Day%' OR column_key LIKE 'Hedge Day%' "
    "ORDER BY client_id, row_index, column_key"
)
rows = cur.fetchall()
print(f"Total farming notes: {len(rows)}\n")

current_client = None
for r in rows:
    if r[0] != current_client:
        current_client = r[0]
        print(f"=== {current_client} ===")
    content = r[3].replace("\n", " | ")
    print(f"  row {r[1]:>4} | {r[2]:<14} | {content:<30} | by: {r[4]} | {r[5]}")

# Also show ALL notes (non-farming too)
print("\n\n--- ALL NOTES (including non-farming) ---")
cur.execute(
    "SELECT client_id, row_index, column_key, note_content, created_by, updated_at "
    "FROM cell_notes "
    "ORDER BY client_id, row_index, column_key"
)
rows = cur.fetchall()
print(f"Total notes: {len(rows)}\n")
current_client = None
for r in rows:
    if r[0] != current_client:
        current_client = r[0]
        print(f"=== {current_client} ===")
    content = r[3].replace("\n", " | ")[:50]
    print(f"  row {r[1]:>4} | {r[2]:<20} | {content:<50} | by: {r[4]}")

conn.close()
