"""Debug script to investigate hedging review discrepancy for Gregory Falk."""
import json, sqlite3

conn = sqlite3.connect('dashboard/dashboard.db')
c = conn.cursor()

# Find Gregory Falk
c.execute("SELECT client_id FROM clients_data")
all_clients = [r[0] for r in c.fetchall()]
matches = [cid for cid in all_clients if 'falk' in cid.lower() or 'gregory' in cid.lower()]
print(f"Matching clients: {matches}")

for client_id in matches:
    c.execute("SELECT account, evaluations, statistics, identity FROM clients_data WHERE client_id = ?", (client_id,))
    row = c.fetchone()
    if not row:
        continue
    acct = json.loads(row[0] or '{}')
    evaluations = json.loads(row[1] or '[]')
    statistics = json.loads(row[2] or '{}')
    identity = json.loads(row[3] or '{}')
    
    print(f"\n{'='*60}")
    print(f"Client: {client_id}")
    print(f"{'='*60}")
    
    # Hedging Review from statistics
    hr = statistics.get('hedging_review', {})
    print("\n=== Hedging Review (from statistics) ===")
    for k, v in hr.items():
        print(f"  {k}: {v}")
    
    # MT5 Account data
    print("\n=== MT5 Account ===")
    print(f"  balance: {acct.get('balance')}")
    print(f"  total_deposits: {acct.get('total_deposits')}")
    print(f"  total_withdrawals: {acct.get('total_withdrawals')}")
    
    # Sheet URL
    sheet_url = identity.get('sheet_url')
    print(f"\n  sheet_url: {sheet_url}")
    
    # Cashflow In-Progress
    cf = statistics.get('cashflow_inprogress', {})
    print("\n=== Cashflow In-Progress (ALL evals, no status filter) ===")
    for k, v in cf.items():
        print(f"  {k}: {v}")
    
    # Manual calculation check
    print("\n=== Manual Recalculation ===")
    balance = float(acct.get('balance', 0) or 0)
    deposits = float(acct.get('total_deposits', 0) or 0)
    withdrawals = float(acct.get('total_withdrawals', 0) or 0)
    net_deposits = deposits + withdrawals
    actual_hedging = balance - net_deposits
    sheet_hedging = cf.get('hedging_results', 0) + cf.get('farming_results', 0)
    
    print(f"  Balance: {balance}")
    print(f"  Deposits: {deposits}")
    print(f"  Withdrawals: {withdrawals}")
    print(f"  Net Deposits (deposits + withdrawals): {net_deposits}")
    print(f"  Actual Hedging (balance - net_deposits): {actual_hedging}")
    print(f"  Sheet Hedging (hedge + farm): {sheet_hedging}")
    print(f"  Discrepancy: {actual_hedging - sheet_hedging}")
    
    # Now let's also check evaluations to see the individual hedge/farm sums
    print(f"\n=== Evaluations: {len(evaluations)} rows ===")
    
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
    HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
    
    def parse_currency(val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s or s == '-' or s == '':
            return 0.0
        s = s.replace('$', '').replace(',', '').replace(' ', '')
        if s.startswith('(') and s.endswith(')'):
            s = '-' + s[1:-1]
        try:
            return float(s)
        except:
            return 0.0
    
    total_p1_hedges = 0
    total_funded_hedges = 0
    total_hedge_days = 0
    
    for i, ev in enumerate(evaluations):
        p1_h = round(sum(parse_currency(ev.get(col)) for col in P1_HEDGE_COLS), 2)
        funded_h = round(sum(parse_currency(ev.get(col)) for col in FUNDED_HEDGE_COLS), 2)
        hdays = round(sum(parse_currency(ev.get(col)) for col in HEDGE_DAY_COLS), 2)
        total_p1_hedges += p1_h
        total_funded_hedges += funded_h
        total_hedge_days += hdays
        
        firm = ev.get('Prop Firm', '?')
        status_p1 = ev.get('Status P1', '')
        status = ev.get('Status', '')
        if p1_h != 0 or funded_h != 0 or hdays != 0:
            print(f"  Row {i}: {firm} | P1={status_p1} | Status={status} | P1_hedge={p1_h} | Funded_hedge={funded_h} | HedgeDays={hdays}")
    
    print(f"\n  Total P1 Hedges: {round(total_p1_hedges, 2)}")
    print(f"  Total Funded Hedges: {round(total_funded_hedges, 2)}")
    print(f"  Total Hedge Days (Farming): {round(total_hedge_days, 2)}")
    print(f"  Total Sheet Hedging (P1+Funded+Farming): {round(total_p1_hedges + total_funded_hedges + total_hedge_days, 2)}")

    # Also check what the user-provided sheet shows
    user_sheet_url = "https://docs.google.com/spreadsheets/d/1in4Z-76-GJ2URCslKafg-RIsY3XNqRLzhcZQKjgFZuQ/edit"

    # Now fetch from Google Sheet to compare
    fetch_url = sheet_url or user_sheet_url
    if fetch_url:
        print(f"\n=== Fetching from Google Sheet to compare ===")
        try:
            import sys
            sys.path.insert(0, '.')
            from utils.data_processor import fetch_evaluations, calculate_statistics
            
            result = fetch_evaluations(fetch_url)
            if isinstance(result, tuple):
                sheet_evals, xlsx_notes = result
            else:
                sheet_evals = result
                xlsx_notes = None
            
            print(f"  Fetched {len(sheet_evals)} evaluations from Google Sheet")
            
            # Calculate stats from sheet data
            sheet_stats = calculate_statistics(sheet_evals, mt5_account=acct, xlsx_notes=xlsx_notes)
            sheet_hr = sheet_stats.get('hedging_review', {})
            sheet_cf = sheet_stats.get('cashflow_inprogress', {})
            
            print(f"\n  === Sheet-based Hedging Review ===")
            for k, v in sheet_hr.items():
                print(f"    {k}: {v}")
            
            print(f"\n  === Sheet-based Cashflow In-Progress ===")
            for k, v in sheet_cf.items():
                print(f"    {k}: {v}")
            
            # Compare evaluations
            print(f"\n  === Comparing DB vs Sheet evaluations ===")
            print(f"  DB eval count: {len(evaluations)}")
            print(f"  Sheet eval count: {len(sheet_evals)}")
            
            # Sum hedge results from sheet
            s_total_p1 = 0
            s_total_funded = 0
            s_total_farming = 0
            for ev in sheet_evals:
                s_total_p1 += round(sum(parse_currency(ev.get(col)) for col in P1_HEDGE_COLS), 2)
                s_total_funded += round(sum(parse_currency(ev.get(col)) for col in FUNDED_HEDGE_COLS), 2)
                s_total_farming += round(sum(parse_currency(ev.get(col)) for col in HEDGE_DAY_COLS), 2)
            
            print(f"  Sheet P1 Hedges: {round(s_total_p1, 2)}")
            print(f"  Sheet Funded Hedges: {round(s_total_funded, 2)}")
            print(f"  Sheet Farming: {round(s_total_farming, 2)}")
            print(f"  Sheet Total: {round(s_total_p1 + s_total_funded + s_total_farming, 2)}")
            
            # Check if the Stats tab has its own hedging values
            if xlsx_notes and '__stats_tab__' in xlsx_notes:
                stats_tab = xlsx_notes['__stats_tab__']
                print(f"\n  === Stats Tab from XLSX ===")
                for k, v in stats_tab.items():
                    if 'hedge' in k.lower() or 'hedging' in k.lower() or 'farm' in k.lower() or 'deposit' in k.lower() or 'withdraw' in k.lower() or 'balance' in k.lower():
                        print(f"    {k}: {v}")
                        
        except Exception as e:
            import traceback
            print(f"  Error fetching sheet: {e}")
            traceback.print_exc()

conn.close()
