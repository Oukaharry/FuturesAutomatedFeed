import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id=?", ('Chris',)).fetchone()
evs = json.loads(row[0])
for i, e in enumerate(evs):
    ac1 = str(e.get('Account #', ''))
    ac2 = str(e.get('Account #.1', ''))
    if '1128' in ac1 + ac2:
        print(f"idx={i} row={i+2} firm={e.get('Prop Firm','?')} ac1={ac1} ac2={ac2} P1={e.get('Status P1','')} F={e.get('Status','')}")
