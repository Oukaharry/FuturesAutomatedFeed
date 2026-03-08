"""Debug script to compare Tyler's dashboard data vs Google Sheet data."""
import sqlite3
import json
import sys
sys.path.insert(0, '.')

from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

# 1. Get Tyler's stored data from local database
print("=" * 60)
print("1. LOCAL DATABASE - Tyler's stored statistics")
print("=" * 60)

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT client_id FROM clients_data WHERE LOWER(client_id) LIKE '%tyler%'")
rows = cur.fetchall()
print(f"Tyler records found: {[r['client_id'] for r in rows]}")

stored_stats = None
tyler_id = None
for r in rows:
    cid = r['client_id']
    tyler_id = cid
    cur.execute("SELECT statistics, evaluations FROM clients_data WHERE client_id = ?", (cid,))
    data = cur.fetchone()
    if data and data['statistics']:
        stored_stats = json.loads(data['statistics'])
        print(f"\ncashflow_inprogress (stored in DB):")
        cf = stored_stats.get('cashflow_inprogress', {})
        print(f"  Challenge Fees:   ${cf.get('challenge_fees', 0):,.2f}")
        print(f"  Hedging Results:  ${cf.get('hedging_results', 0):,.2f}")
        print(f"  Farming Results:  ${cf.get('farming_results', 0):,.2f}")
        print(f"  Payouts:          ${cf.get('payouts', 0):,.2f}")
        print(f"  Net Profit:       ${cf.get('net_profit', 0):,.2f}")
        
        hr = stored_stats.get('hedging_review', {})
        print(f"\nHedging Review:")
        print(f"  Discrepancy:      ${hr.get('discrepancy', 0):,.2f}")
        print(f"  Sheet Hedging:    ${hr.get('sheet_hedging_results', 0):,.2f}")
        print(f"  Actual Hedging:   ${hr.get('actual_hedging_results', 0):,.2f}")
    
    # Get stored evaluations
    if data and data['evaluations']:
        stored_evals = json.loads(data['evaluations'])
        print(f"\nStored evaluations count: {len(stored_evals)}")

conn.close()

# 2. Fetch fresh data from Tyler's Google Sheet
print("\n" + "=" * 60)
print("2. GOOGLE SHEET - Fresh fetch from Tyler's sheet")
print("=" * 60)

# The user provided this sheet URL
TYLER_SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"
sheet_url = f"https://docs.google.com/spreadsheets/d/{TYLER_SHEET_ID}/export?format=csv"

print(f"Fetching from: {sheet_url}")
try:
    result = fetch_evaluations(sheet_url)
    if isinstance(result, tuple):
        fresh_evals, fresh_notes = result
    else:
        fresh_evals = result
        fresh_notes = {}
except Exception as e:
    print(f"ERROR fetching sheet: {e}")
    print("Trying with full edit URL...")
    try:
        result = fetch_evaluations(f"https://docs.google.com/spreadsheets/d/{TYLER_SHEET_ID}/edit?gid=0#gid=0")
        if isinstance(result, tuple):
            fresh_evals, fresh_notes = result
        else:
            fresh_evals = result
            fresh_notes = {}
    except Exception as e2:
        print(f"ERROR with edit URL too: {e2}")
        fresh_evals = []
print(f"Fresh evaluations count: {len(fresh_evals)}")

# Calculate fresh statistics
fresh_stats = calculate_statistics(fresh_evals)
cf_fresh = fresh_stats.get('cashflow_inprogress', {})
print(f"\ncashflow_inprogress (freshly calculated from sheet):")
print(f"  Challenge Fees:   ${cf_fresh.get('challenge_fees', 0):,.2f}")
print(f"  Hedging Results:  ${cf_fresh.get('hedging_results', 0):,.2f}")
print(f"  Farming Results:  ${cf_fresh.get('farming_results', 0):,.2f}")
print(f"  Payouts:          ${cf_fresh.get('payouts', 0):,.2f}")
print(f"  Net Profit:       ${cf_fresh.get('net_profit', 0):,.2f}")

# 3. Now get STORED evaluations and recalculate
print("\n" + "=" * 60)
print("3. RECALCULATE from stored evaluations in DB")
print("=" * 60)

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations, account FROM clients_data WHERE client_id = ?", (tyler_id,))
data = cur.fetchone()
conn.close()

if data and data['evaluations']:
    stored_evals = json.loads(data['evaluations'])
    mt5_account = json.loads(data['account']) if data['account'] else None
    recalc_stats = calculate_statistics(stored_evals, mt5_account=mt5_account)
    cf_recalc = recalc_stats.get('cashflow_inprogress', {})
    print(f"\ncashflow_inprogress (recalculated from stored evals + MT5):")
    print(f"  Challenge Fees:   ${cf_recalc.get('challenge_fees', 0):,.2f}")
    print(f"  Hedging Results:  ${cf_recalc.get('hedging_results', 0):,.2f}")
    print(f"  Farming Results:  ${cf_recalc.get('farming_results', 0):,.2f}")
    print(f"  Payouts:          ${cf_recalc.get('payouts', 0):,.2f}")
    print(f"  Net Profit:       ${cf_recalc.get('net_profit', 0):,.2f}")
    
    hr = recalc_stats.get('hedging_review', {})
    print(f"\n  Discrepancy:      ${hr.get('discrepancy', 0):,.2f}")

# 4. Compare side by side
print("\n" + "=" * 60)
print("4. COMPARISON: Dashboard (stored) vs Google Sheet (fresh)")
print("=" * 60)

if stored_stats and fresh_stats:
    cf_stored = stored_stats.get('cashflow_inprogress', {})
    fields = ['challenge_fees', 'hedging_results', 'farming_results', 'payouts', 'net_profit']
    print(f"{'Field':<20} {'Dashboard':>15} {'Sheet (fresh)':>15} {'Difference':>15}")
    print("-" * 65)
    for f in fields:
        v1 = cf_stored.get(f, 0)
        v2 = cf_fresh.get(f, 0)
        diff = v1 - v2
        flag = " ***" if abs(diff) > 0.01 else ""
        print(f"{f:<20} ${v1:>13,.2f} ${v2:>13,.2f} ${diff:>13,.2f}{flag}")

# 5. Row-by-row comparison of evaluations
print("\n" + "=" * 60)
print("5. ROW-BY-ROW DIFF: Stored evals vs Fresh evals")
print("=" * 60)

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (tyler_id,))
data = cur.fetchone()
conn.close()

if data and data['evaluations']:
    stored_evals = json.loads(data['evaluations'])
    
    print(f"Stored eval count: {len(stored_evals)}, Fresh eval count: {len(fresh_evals)}")
    
    # Compare key fields per row
    max_rows = max(len(stored_evals), len(fresh_evals))
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
    HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
    
    total_fee_diff = 0
    total_hedge_diff = 0
    total_farm_diff = 0
    total_payout_diff = 0
    
    for i in range(max_rows):
        s_ev = stored_evals[i] if i < len(stored_evals) else None
        f_ev = fresh_evals[i] if i < len(fresh_evals) else None
        
        if s_ev and f_ev:
            s_fee = parse_currency(s_ev.get('Fee')) + parse_currency(s_ev.get('Activation Fee'))
            f_fee = parse_currency(f_ev.get('Fee')) + parse_currency(f_ev.get('Activation Fee'))
            
            s_hedge = sum(parse_currency(s_ev.get(c)) for c in P1_HEDGE_COLS) + sum(parse_currency(s_ev.get(c)) for c in FUNDED_HEDGE_COLS)
            f_hedge = sum(parse_currency(f_ev.get(c)) for c in P1_HEDGE_COLS) + sum(parse_currency(f_ev.get(c)) for c in FUNDED_HEDGE_COLS)
            
            s_farm = sum(parse_currency(s_ev.get(c)) for c in HEDGE_DAY_COLS)
            f_farm = sum(parse_currency(f_ev.get(c)) for c in HEDGE_DAY_COLS)
            
            s_payout = sum(parse_currency(s_ev.get(f'Payout {j}')) for j in range(1, 5))
            f_payout = sum(parse_currency(f_ev.get(f'Payout {j}')) for j in range(1, 5))
            
            fee_diff = s_fee - f_fee
            hedge_diff = s_hedge - f_hedge
            farm_diff = s_farm - f_farm
            payout_diff = s_payout - f_payout
            
            total_fee_diff += fee_diff
            total_hedge_diff += hedge_diff
            total_farm_diff += farm_diff
            total_payout_diff += payout_diff
            
            if abs(fee_diff) > 0.01 or abs(hedge_diff) > 0.01 or abs(farm_diff) > 0.01 or abs(payout_diff) > 0.01:
                account = s_ev.get('Prop Firm', '?') + ' ' + str(s_ev.get('Account Size', '?'))
                print(f"\nRow {i}: {account}")
                if abs(fee_diff) > 0.01:
                    print(f"  Fee:     stored=${s_fee:,.2f}  fresh=${f_fee:,.2f}  diff=${fee_diff:,.2f}")
                if abs(hedge_diff) > 0.01:
                    print(f"  Hedge:   stored=${s_hedge:,.2f}  fresh=${f_hedge:,.2f}  diff=${hedge_diff:,.2f}")
                if abs(farm_diff) > 0.01:
                    print(f"  Farm:    stored=${s_farm:,.2f}  fresh=${f_farm:,.2f}  diff=${farm_diff:,.2f}")
                if abs(payout_diff) > 0.01:
                    print(f"  Payout:  stored=${s_payout:,.2f}  fresh=${f_payout:,.2f}  diff=${payout_diff:,.2f}")
        elif s_ev and not f_ev:
            print(f"\nRow {i}: EXTRA in stored (not in sheet): {s_ev.get('Prop Firm', '?')}")
        elif f_ev and not s_ev:
            print(f"\nRow {i}: MISSING from stored (in sheet): {f_ev.get('Prop Firm', '?')}")
    
    print(f"\n--- TOTAL DIFFS ---")
    print(f"  Fee diff total:     ${total_fee_diff:,.2f}")
    print(f"  Hedge diff total:   ${total_hedge_diff:,.2f}")
    print(f"  Farm diff total:    ${total_farm_diff:,.2f}")
    print(f"  Payout diff total:  ${total_payout_diff:,.2f}")
