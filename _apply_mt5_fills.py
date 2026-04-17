"""Apply 5 hedge result fills from MT5 report to DB."""
import sqlite3, json

db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

fills = [
    (358, 'Hedge Result 2', '$383.12'),
    (386, 'Hedge Result 2', '$-147.28'),
    (404, 'Hedge Result 2', '$-150.14'),
    (386, 'Hedge Result 3', '$-231.44'),
    (404, 'Hedge Result 3', '$-235.14'),
]

applied = 0
for idx, col, val in fills:
    ev = evals[idx]
    acct = ev.get('Account #', '')
    old_val = str(ev.get(col, '')).strip()
    if old_val and old_val != 'nan':
        print(f"  SKIP Row {idx} {col}: already has '{old_val}' (acct={acct})")
        continue
    ev[col] = val
    applied += 1
    print(f"  SET  Row {idx} {col} = {val} (acct={acct})")

if applied:
    db.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
    db.commit()
    print(f"\nApplied {applied} fills to DB.")
else:
    print("\nNo fills needed.")

db.close()
