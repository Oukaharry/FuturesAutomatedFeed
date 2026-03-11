import sqlite3, json, datetime
conn = sqlite3.connect('dashboard/dashboard.db')
row = conn.execute('SELECT deals FROM clients_data WHERE client_id=?', ('Chris',)).fetchone()
deals = json.loads(row[0])
print(f"Total deals: {len(deals)}")
print("\nDeals matching account 86721:")
for d in deals:
    comment = str(d.get('comment', ''))
    if '86721' in comment:
        ts = d.get('time', 0)
        try:
            dt = datetime.datetime.fromtimestamp(int(ts)) if ts else 'N/A'
        except:
            dt = ts
        p = d.get('profit', 0)
        tp = d.get('type', '?')
        sym = d.get('symbol', '?')
        vol = d.get('volume', 0)
        print(f"  {dt}  profit={p}  type={tp}  symbol={sym}  vol={vol}  comment={comment}")
conn.close()
