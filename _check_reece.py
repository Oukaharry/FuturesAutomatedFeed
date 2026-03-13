import sqlite3, json, os

DB_PATH = os.path.join('dashboard', 'dashboard.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Find Reece
rows = conn.execute("SELECT client_id FROM clients_data WHERE LOWER(client_id) LIKE '%reece%'").fetchall()
if not rows:
    all_ids = [r['client_id'] for r in conn.execute("SELECT client_id FROM clients_data").fetchall()]
    print("All client_ids:", all_ids)
else:
    for r in rows:
        cid = r['client_id']
        print(f"Client: {cid}")

        row = conn.execute("SELECT account, statistics FROM clients_data WHERE client_id = ?", (cid,)).fetchone()

        # Raw MT5 account
        if row['account']:
            acct = json.loads(row['account'])
            print(f"\nRaw MT5 Account (clients_data.account):")
            print(f"  balance: {acct.get('balance')}")
            print(f"  total_deposits: {acct.get('total_deposits')}")
            print(f"  total_withdrawals: {acct.get('total_withdrawals')}")
            print(f"  login: {acct.get('login')}")

        # Statistics
        if row['statistics']:
            stats = json.loads(row['statistics'])
            hr = stats.get('hedging_review', {})
            print(f"\nHedging Review (from statistics):")
            for k, v in sorted(hr.items()):
                if not k.startswith('_debug') and k != 'historical_accounts':
                    print(f"  {k}: {v}")

            hist = hr.get('historical_accounts', [])
            if hist:
                print(f"\nHistorical Accounts ({len(hist)}):")
                for h in hist:
                    print(f"  {h.get('name','?')}: deposits={h.get('deposits')}, withdrawals={h.get('withdrawals')}, balance={h.get('balance')}")

            cf = stats.get('cashflow_inprogress', {})
            print(f"\nCashflow In-Progress:")
            print(f"  hedging_results: {cf.get('hedging_results')}")
            print(f"  farming_results: {cf.get('farming_results')}")
            print(f"  challenge_fees: {cf.get('challenge_fees')}")
            print(f"  payouts: {cf.get('payouts')}")
            print(f"  net_profit: {cf.get('net_profit')}")

            # Verify the formula
            d = hr.get('discrepancy', 0)
            expected_np = cf.get('payouts', 0) + cf.get('hedging_results', 0) + cf.get('farming_results', 0) - cf.get('challenge_fees', 0) + d
            print(f"\n  Verification: payouts({cf.get('payouts',0)}) + hedging({cf.get('hedging_results',0)}) + farming({cf.get('farming_results',0)}) - fees({cf.get('challenge_fees',0)}) + discrepancy({d}) = {expected_np}")
            print(f"  Stored net_profit: {cf.get('net_profit')}")

conn.close()
