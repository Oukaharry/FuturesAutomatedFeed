import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')

for row in conn.execute("SELECT client_id, evaluations FROM clients_data").fetchall():
    cid = row[0]
    evs = json.loads(row[1])
    for j, e in enumerate(evs[:10]):
        day_vals = {k: v for k, v in e.items() if ('Hedge Day' in k or 'Prop Day' in k) and v}
        if day_vals:
            print(f"{cid} Row {j}: {day_vals}")
            break
    else:
        continue
    break
