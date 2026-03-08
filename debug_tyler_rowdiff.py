"""Debug: Compare stored evals vs fresh evals row-by-row to find what changed."""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

TYLER_SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"
sheet_url = f"https://docs.google.com/spreadsheets/d/{TYLER_SHEET_ID}/edit?gid=0#gid=0"

# Get stored evals
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()
stored_evals = json.loads(data['evaluations'])

# Get fresh evals
result = fetch_evaluations(sheet_url)
fresh_evals = result[0] if isinstance(result, tuple) else result

print(f"Stored: {len(stored_evals)} rows, Fresh: {len(fresh_evals)} rows")

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

# Find rows that differ
max_rows = max(len(stored_evals), len(fresh_evals))
diffs_found = 0
for i in range(max_rows):
    s = stored_evals[i] if i < len(stored_evals) else None
    f = fresh_evals[i] if i < len(fresh_evals) else None
    
    if s and f:
        s_fee = parse_currency(s.get('Fee')) + parse_currency(s.get('Activation Fee'))
        f_fee = parse_currency(f.get('Fee')) + parse_currency(f.get('Activation Fee'))
        
        s_hedge = sum(parse_currency(s.get(c)) for c in P1_HEDGE_COLS + FUNDED_HEDGE_COLS)
        f_hedge = sum(parse_currency(f.get(c)) for c in P1_HEDGE_COLS + FUNDED_HEDGE_COLS)
        
        s_payout = sum(parse_currency(s.get(f'Payout {j}')) for j in range(1, 5))
        f_payout = sum(parse_currency(f.get(f'Payout {j}')) for j in range(1, 5))
        
        if abs(s_fee - f_fee) > 0.01 or abs(s_hedge - f_hedge) > 0.01 or abs(s_payout - f_payout) > 0.01:
            diffs_found += 1
            firm = f.get('Prop Firm', '?')
            size = f.get('Account Size', '?')
            print(f"\n--- Row {i}: {firm} {size} ---")
            if abs(s_fee - f_fee) > 0.01:
                print(f"  Fee+Act: stored={s_fee:.2f}, fresh={f_fee:.2f}, diff={s_fee-f_fee:.2f}")
                print(f"    stored Fee='{s.get('Fee')}' Act='{s.get('Activation Fee')}'")
                print(f"    fresh  Fee='{f.get('Fee')}' Act='{f.get('Activation Fee')}'")
            if abs(s_hedge - f_hedge) > 0.01:
                print(f"  Hedges: stored={s_hedge:.2f}, fresh={f_hedge:.2f}, diff={s_hedge-f_hedge:.2f}")
                for c in P1_HEDGE_COLS + FUNDED_HEDGE_COLS:
                    sv = parse_currency(s.get(c))
                    fv = parse_currency(f.get(c))
                    if abs(sv - fv) > 0.01:
                        print(f"    {c}: stored='{s.get(c)}'({sv:.2f}), fresh='{f.get(c)}'({fv:.2f})")
            if abs(s_payout - f_payout) > 0.01:
                print(f"  Payouts: stored={s_payout:.2f}, fresh={f_payout:.2f}, diff={s_payout-f_payout:.2f}")
                for j in range(1, 5):
                    sv = parse_currency(s.get(f'Payout {j}'))
                    fv = parse_currency(f.get(f'Payout {j}'))
                    if abs(sv - fv) > 0.01:
                        print(f"    Payout {j}: stored='{s.get(f'Payout {j}')}'({sv:.2f}), fresh='{f.get(f'Payout {j}')}'({fv:.2f})")
    elif s and not f:
        print(f"\nRow {i}: EXISTS in stored, MISSING from fresh - {s.get('Prop Firm','?')}")
        diffs_found += 1
    elif f and not s:
        print(f"\nRow {i}: MISSING from stored, EXISTS in fresh - {f.get('Prop Firm','?')}")
        diffs_found += 1

print(f"\n\nTotal differing rows: {diffs_found}")
