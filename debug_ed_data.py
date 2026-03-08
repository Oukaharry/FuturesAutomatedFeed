import sqlite3, json, os, glob

# Find the database file
db_candidates = list(set(glob.glob('dashboard/*.db') + glob.glob('*.db')))
print("DB files found:", db_candidates)

for db_path in db_candidates:
    print(f"\n=== {db_path} ===")
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables: {tables}")
    
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        if 'evaluations' in cols or 'client_id' in cols:
            print(f"  Table {t}: {cols}")
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"    Row count: {cur.fetchone()[0]}")
            
            if 'evaluations' in cols:
                cur.execute(f"SELECT client_id, evaluations, last_updated FROM {t} WHERE LOWER(client_id) LIKE '%ed%'")
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        evals = json.loads(r[1]) if r[1] else []
                        print(f"    Client: {r[0]}, Updated: {r[2]}, Evaluations: {len(evals)}")
                        for i, e in enumerate(evals):
                            acct = e.get('Account #', 'N/A')
                            acct2 = e.get('Account #.1', 'N/A')
                            prop = e.get('Prop Firm', 'N/A')
                            status = e.get('Status', 'N/A')
                            acct_size = e.get('Account Size', 'N/A')
                            phase = e.get('Phase', 'N/A')
                            print(f"      [{i}] Prop={prop} | AcctNum={acct} | Acct#.1={acct2} | Size={acct_size} | Phase={phase} | Status={status}")
                else:
                    # Show all client IDs
                    cur.execute(f"SELECT client_id FROM {t}")
                    clients = [r[0] for r in cur.fetchall()]
                    print(f"    All client_ids: {clients}")
    db.close()
rows = cur.fetchall()

if not rows:
    print("No data found for 'Ed'. Listing all client_ids:")
    cur.execute("SELECT client_id FROM clients_data")
    for r in cur.fetchall():
        print(f"  - {r[0]}")
else:
    for r in rows:
        evals = json.loads(r[1]) if r[1] else []
        print(f"Client: {r[0]}, Updated: {r[2]}, Evaluations: {len(evals)}")
        for i, e in enumerate(evals):
            acct = e.get('Account #', 'N/A')
            acct2 = e.get('Account #.1', 'N/A')
            prop = e.get('Prop Firm', 'N/A')
            status = e.get('Status', 'N/A')
            acct_size = e.get('Account Size', 'N/A')
            phase = e.get('Phase', 'N/A')
            print(f"  [{i}] Prop={prop} | AcctNum={acct} | Acct#.1={acct2} | Size={acct_size} | Phase={phase} | Status={status}")

db.close()
