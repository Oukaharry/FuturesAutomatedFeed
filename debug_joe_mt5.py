"""Check Joe's MT5/discrepancy data and DB table schema."""
import json, sys; sys.path.insert(0, '.')
from dashboard.database import get_connection

with get_connection() as conn:
    # Get table columns
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients_data)").fetchall()]
    print("Table columns:", cols)
    row = conn.execute('SELECT * FROM clients_data WHERE client_id=?', ('Joe',)).fetchone()

print()
print("Non-null fields:")
for i, col in enumerate(cols):
    val = row[i]
    if val and val not in ('null', 'None', '{}', '[]', ''):
        if isinstance(val, str) and len(val) > 100:
            print(f"  {col}: [length={len(val)}]")
        else:
            print(f"  {col}: {val}")

# Check statistics discrepancy
s = json.loads(row[cols.index('statistics')])
print()
print("hedging_review:", json.dumps(s.get('hedging_review', {}), indent=2)[:800])
