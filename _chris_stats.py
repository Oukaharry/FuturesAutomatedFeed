import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

CLIENT_ID = 'Chris'

# Get stored statistics from clients_data
cur.execute("SELECT statistics, evaluations FROM clients_data WHERE client_id = ?", (CLIENT_ID,))
row = cur.fetchone()
if row:
    stats = json.loads(row['statistics']) if row['statistics'] else {}
    print("=== STATISTICS ===")
    print(json.dumps(stats, indent=2))

    evals = json.loads(row['evaluations']) if row['evaluations'] else []
    print(f"\n=== EVALUATIONS ({len(evals)} rows) ===")
    # Show summary of each eval row
    for i, ev in enumerate(evals):
        hedge_keys = [k for k in ev.keys() if 'hedge' in k.lower() and ev[k] is not None and ev[k] != '' and ev[k] != 0]
        firm = ev.get('Prop Firm', '?')
        size = ev.get('Account Size', '?')
        status_p1 = ev.get('Status P1', '?')
        status_funded = ev.get('Status', '?')
        hedge_net = ev.get('Hedge Net', '')
        hedge_net_1 = ev.get('Hedge Net.1', '')
        payout1 = ev.get('Payout 1', '')
        farming = ev.get('Farming Net', '')
        print(f"  [{i}] {firm} {size} | P1={status_p1} Fund={status_funded} | HedgeNet={hedge_net} HedgeNet.1={hedge_net_1} | Payout1={payout1} | Farming={farming}")
        # Show all hedge results
        for k in sorted(ev.keys()):
            if 'hedge result' in k.lower() and ev[k] is not None and ev[k] != '':
                print(f"       {k}: {ev[k]}")
else:
    print("No data found for Chris")

# Daily watermarks
cur.execute("SELECT COUNT(*) as cnt FROM daily_watermarks WHERE client_id = ?", (CLIENT_ID,))
print(f"\n=== Daily Watermarks: {cur.fetchone()['cnt']} records ===")

# Waterlog periods
cur.execute("SELECT * FROM waterlog_periods WHERE client_id = ? ORDER BY from_date", (CLIENT_ID,))
periods = cur.fetchall()
print(f"\n=== Waterlog Periods ({len(periods)}) ===")
for p in periods:
    print(f"  {p['from_date']} -> {p['to_date']} | low={p['period_low']} high={p['period_high']} split={p['split_pct']}")

conn.close()
