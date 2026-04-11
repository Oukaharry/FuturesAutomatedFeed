import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts._compare_mt5_vs_db import DATABASE_URL, parse_num
import psycopg2

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id = %s", ("Rob Madsen",))
rows = cur.fetchone()[0]
cur.close(); conn.close()

for ev in rows:
    if not isinstance(ev, dict): continue
    acct = str(ev.get("Account Number", ""))
    if "29342" in acct:
        print("Account:", acct)
        for k, v in ev.items():
            if "hedge" in k.lower():
                print(f"  {k!r}: {v!r}  ->  parse_num={parse_num(v)}")
        break
