"""Check actual eval dict keys for specific Tradeify account."""
import psycopg2, json
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect('postgresql://postgres:postgres123@localhost:5432/tradeopss')
cur = conn.cursor(cursor_factory=RealDictCursor)

# Search ALL clients for this specific account
cur.execute("SELECT client_id, evaluations FROM clients_data WHERE evaluations::text LIKE '%TDFYSL50280105241%'")
rows = cur.fetchall()
print(f"Found {len(rows)} rows with TDFYSL50280105241")

if not rows:
    # Try broader search
    cur.execute("SELECT client_id, evaluations FROM clients_data WHERE evaluations::text LIKE '%TDFYSL502%'")
    rows = cur.fetchall()
    print(f"Found {len(rows)} rows with TDFYSL502")

for row in rows:
    evals_raw = row['evaluations']
    evals = json.loads(evals_raw) if isinstance(evals_raw, str) else evals_raw
    for ev in evals:
        acct = ev.get('Account #', '') or ''
        if 'TDFYSL502' in acct.upper():
            all_keys = sorted(ev.keys())
            hedge_keys = sorted([k for k in ev.keys() if 'hedge' in k.lower() or 'result' in k.lower()])
            print(f"\nClient: {row['client_id']}")
            print(f"Account: {acct}")
            print(f"  Status P1: {ev.get('Status P1')!r}")
            print(f"  Status: {ev.get('Status')!r}")
            print(f"  Account #.1: {ev.get('Account #.1')!r}")
            print(f"  Total keys: {len(all_keys)}")
            print(f"  ALL keys: {all_keys}")
            print(f"  Hedge/Result keys: {hedge_keys}")
            for hk in hedge_keys:
                val = ev.get(hk)
                print(f"    {hk} = {val!r}")

conn.close()
