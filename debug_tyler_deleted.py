"""Check deleted rows and their fee values."""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import parse_currency

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()
evals = json.loads(data['evaluations'])

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

deleted_fee_total = 0.0
deleted_hedge_total = 0.0
deleted_payout_total = 0.0
for i, ev in enumerate(evals):
    status_p1 = str(ev.get('Status P1', '')).strip().lower()
    status_f = str(ev.get('Status') or ev.get('Status Funded', '')).strip().lower()
    
    if 'deleted' in status_p1 or 'deleted' in status_f:
        fee = parse_currency(ev.get('Fee')) + parse_currency(ev.get('Activation Fee'))
        hedge = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS + FUNDED_HEDGE_COLS)
        payout = sum(parse_currency(ev.get(f'Payout {j}')) for j in range(1, 5))
        
        print(f"Row {i}: DELETED - {ev.get('Prop Firm','')} {ev.get('Account Size','')}")
        print(f"  Status P1='{ev.get('Status P1','')}', Status='{ev.get('Status','')}'")
        print(f"  Fee=${fee:.2f}, Hedge=${hedge:.2f}, Payout=${payout:.2f}")
        
        deleted_fee_total += fee
        deleted_hedge_total += hedge
        deleted_payout_total += payout

print(f"\n--- DELETED TOTALS ---")
print(f"Total deleted fees:    ${deleted_fee_total:.2f}")
print(f"Total deleted hedges:  ${deleted_hedge_total:.2f}")
print(f"Total deleted payouts: ${deleted_payout_total:.2f}")

print(f"\n--- IMPACT ON CASHFLOW CALC ---")
print(f"All rows Fee+Act:     $61,234.37")
print(f"Minus deleted fees:   ${61234.37 - deleted_fee_total:.2f}")
print(f"Code calculates:      $60,731.37")
print(f"Match: {abs(61234.37 - deleted_fee_total - 60731.37) < 0.02}")

print(f"\nAll rows Hedges:      -$26,646.11")
print(f"Minus deleted hedges: ${-26646.11 - deleted_hedge_total:.2f}")
print(f"Code calculates:      -$26,236.11")
print(f"Match: {abs(-26646.11 - deleted_hedge_total - (-26236.11)) < 0.02}")
