#!/usr/bin/env python3
"""Quick lookup: show Chris Ream eval rows by display number."""
import sqlite3, json, os

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
conn = sqlite3.connect(DB_PATH)
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris Ream'").fetchone()
conn.close()

evals = json.loads(row[0])

# Dashboard display logic:
# rowsToRender sorted by originalIndex descending
# displayNum = totalVisible - i  (where i=0 is the highest originalIndex)
# So display N = DB index (N - 1) when no deleted rows

# Filter out deleted rows
visible = [(i, ev) for i, ev in enumerate(evals) if not ev.get('_deleted')]
visible.sort(key=lambda x: x[0], reverse=True)  # highest index first
total = len(visible)
# assign display numbers
display_map = {}
for i, (db_idx, ev) in enumerate(visible):
    display_num = total - i
    display_map[display_num] = (db_idx, ev)

# Show rows 627-640 (visible in screenshot + surrounds)
print(f"Chris Ream: {len(evals)} total evals, {total} visible (non-deleted)")
print(f"\n{'Disp#':>5} {'DB Idx':>6}  {'Prop Firm':<20} {'Account Number':<25} {'Account Size':<12} {'Status P1':<15} {'Hedge Result 1':<15}")
print("-" * 120)
for d in range(640, 620, -1):
    if d in display_map:
        db_idx, ev = display_map[d]
        firm = ev.get('Prop Firm', '')
        acct = ev.get('Account Number', '')
        size = ev.get('Account Size', '')
        status = ev.get('Status P1', '')
        hr1 = ev.get('Hedge Result 1', '')
        print(f"{d:>5} {db_idx:>6}  {firm:<20} {acct:<25} {size:<12} {status:<15} {hr1:<15}")
