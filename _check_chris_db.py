import sqlite3, json, re, os

db = sqlite3.connect('dashboard/dashboard.db')
cur = db.cursor()

# Get Chris's evaluations
cur.execute("SELECT client_id, evaluations FROM clients_data WHERE client_id LIKE '%Chris%'")
rows = cur.fetchall()
for name, evals_json in rows:
    evals = json.loads(evals_json) if evals_json else []
    print(f'{name}: {len(evals)} evaluations')
    
    # Check what the fixed CSV has
    fixed_csv_path = os.path.expanduser(r'~\Downloads\Chris_evaluations_fixed.csv')
    if os.path.exists(fixed_csv_path):
        import csv
        with open(fixed_csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fixed_rows = list(reader)
        print(f'Fixed CSV has: {len(fixed_rows)} rows')
    
    # Look at history to understand duplication timeline
    cur.execute("SELECT version, action, change_description, created_at FROM data_history WHERE client_id=? ORDER BY version DESC LIMIT 15", (name,))
    print('\nRecent history:')
    for h in cur.fetchall():
        print(f'  v{h[0]} [{h[1]}] {h[2]} @ {h[3]}')
    
    # Analyze duplicates - check for rows with same Prop Firm + Account Size + Date Purchased
    seen = {}
    dupes = 0
    for i, ev in enumerate(evals):
        key = (
            ev.get('Prop Firm', ''),
            ev.get('Account Size', ''),
            ev.get('Date Purchased', ''),
            ev.get('Date Started', ''),
            ev.get('Fee', '')
        )
        if key in seen:
            dupes += 1
        else:
            seen[key] = i
    print(f'\nDuplicate rows (same Firm+Size+DatePurchased+DateStarted+Fee): {dupes}')
    print(f'Unique rows: {len(seen)}')

db.close()
