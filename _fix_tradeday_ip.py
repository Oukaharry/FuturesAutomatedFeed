"""Remove the 7 In Progress TradeDay rows (614, 615, 627-630, 634) from Chris's DB.
These are empty placeholders from a corrupted CSV import. Chris doesn't trade TradeDay
since moving to the dashboard. The TDF accounts on them are from other clients' logs."""
import json, sqlite3, csv, copy

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

print(f'Before: {len(evals)} evaluations')

# Find In Progress TradeDay rows
td_ip_indices = []
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    if firm == 'TradeDay' and status == 'In Progress':
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        td_ip_indices.append(i)
        print(f'  Removing row {i}: Acct#={a}  Acct#.1={a1}')

# Remove them (reverse order to preserve indices)
new_evals = [ev for i, ev in enumerate(evals) if i not in set(td_ip_indices)]
print(f'\nAfter: {len(new_evals)} evaluations (removed {len(td_ip_indices)})')

# Verify no In Progress TradeDay remains
remaining = sum(1 for ev in new_evals 
    if (ev.get('Prop Firm') or '').strip() == 'TradeDay' 
    and (ev.get('Status P1') or '').strip() == 'In Progress')
print(f'Remaining In Progress TradeDay: {remaining}')

# Count all TradeDay rows (historical should still be there)
total_td = sum(1 for ev in new_evals if (ev.get('Prop Firm') or '').strip() == 'TradeDay')
print(f'Total TradeDay rows (historical): {total_td}')

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
            (json.dumps(new_evals),))
db.commit()
db.close()
print(f'\nDB updated: {len(new_evals)} evaluations')

# Also update the CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    csv_rows = list(reader)

print(f'\nCSV before: {len(csv_rows)} rows')
new_csv_rows = [row for i, row in enumerate(csv_rows) if i not in set(td_ip_indices)]
print(f'CSV after: {len(new_csv_rows)} rows')

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(new_csv_rows)

print(f'CSV updated: {CSV_PATH}')
