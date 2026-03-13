"""Check EXACTLY which rows have Prop Day notes and what the visible top rows look like"""
from dashboard.database import get_connection
from dashboard.notes_service import get_client_notes
import json

with get_connection() as conn:
    cur = conn.cursor()
    
    # Get all Prop Day notes for Ed
    cur.execute("""
        SELECT row_index, column_key, note_content 
        FROM cell_notes 
        WHERE client_id = 'Ed' AND column_key LIKE 'Prop Day%'
        ORDER BY row_index DESC
    """)
    rows = cur.fetchall()
    
    print(f"=== All Prop Day notes for Ed ({len(rows)} total) ===")
    current_row = None
    for r in rows:
        rid, col, content = r[0], r[1], r[2]
        if rid != current_row:
            current_row = rid
            print(f"\n  Row index {rid} (displayed as #{rid + 1}):")
        content_preview = content.replace('\n', ' | ')[:60]
        print(f"    {col}: {content_preview}")
    
    # Check the top 20 rows by index (these are the ones shown first in the table)
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    evals = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    
    print(f"\n\n=== Top 20 rows (newest, shown first in table) ===")
    for idx in range(len(evals)-1, max(len(evals)-21, -1), -1):
        ev = evals[idx]
        prop_firm = ev.get('Prop Firm', 'N/A')
        prop_day1 = ev.get('Prop Day 1', '')
        print(f"  #{idx+1} (idx={idx}): {prop_firm}, Prop Day 1={prop_day1}")
    
    # Total notes count
    cur.execute("SELECT COUNT(*) FROM cell_notes WHERE client_id = 'Ed'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT row_index) FROM cell_notes WHERE client_id = 'Ed' AND column_key LIKE 'Prop Day%'")
    rows_with_prop = cur.fetchone()[0]
    print(f"\n=== Summary ===")
    print(f"Total notes for Ed: {total}")
    print(f"Distinct rows with Prop Day notes: {rows_with_prop}")
    print(f"Total evaluations: {len(evals)}")
