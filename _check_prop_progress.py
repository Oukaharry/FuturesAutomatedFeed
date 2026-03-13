from dashboard.database import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM cell_notes")
    print("Total notes:", cur.fetchone()[0])
    
    cur.execute("SELECT COUNT(*) FROM cell_notes WHERE column_key LIKE 'Prop Day%'")
    print("Prop Day notes:", cur.fetchone()[0])
    
    cur.execute("SELECT DISTINCT column_key FROM cell_notes ORDER BY column_key")
    print("All column keys:", [r[0] for r in cur.fetchall()])
    
    cur.execute("SELECT client_id, row_index, column_key, note_content FROM cell_notes WHERE column_key LIKE 'Prop Day%' LIMIT 20")
    rows = cur.fetchall()
    print(f"\nProp Day note samples ({len(rows)}):")
    for r in rows:
        print(f"  client={r[0]}, row={r[1]}, col={r[2]}, content={r[3]}")

    # Also check: is there a 'Prop Progress' column key?
    cur.execute("SELECT COUNT(*) FROM cell_notes WHERE column_key LIKE 'Prop Progress%'")
    print(f"\nProp Progress notes: {cur.fetchone()[0]}")
    
    # Check what client 'Ed' has
    cur.execute("SELECT client_id, row_index, column_key, note_content FROM cell_notes WHERE client_id = 'Ed' LIMIT 30")
    rows = cur.fetchall()
    print(f"\nEd's notes ({len(rows)}):")
    for r in rows:
        print(f"  row={r[1]}, col={r[2]}, content={r[3]}")
