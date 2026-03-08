"""Verify fixed calculation matches Google Sheet Stats tab."""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import calculate_statistics

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations, account, deals FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()

evals = json.loads(data['evaluations'])
mt5_account = json.loads(data['account']) if data['account'] else None
mt5_deals = json.loads(data['deals']) if data['deals'] else None

new_stats = calculate_statistics(evals, mt5_deals, mt5_account)
cf = new_stats['cashflow_inprogress']

print("=== RECALCULATED (after fix) ===")
print(f"  Challenge Fees:   ${cf['challenge_fees']:,.2f}")
print(f"  Hedging Results:  ${cf['hedging_results']:,.2f}")
print(f"  Farming Results:  ${cf['farming_results']:,.2f}")
print(f"  Payouts:          ${cf['payouts']:,.2f}")
print(f"  Net Profit:       ${cf['net_profit']:,.2f}")

print(f"\n=== GOOGLE SHEET STATS TAB (from screenshot) ===")
print(f"  Challenge Fees:   -$61,234.37")
print(f"  Hedging Results:  -$26,644.42")
print(f"  Farming Results:   $10,794.66")
print(f"  Payouts:          $145,295.20")
print(f"  Net Profit:        $68,211.07")

print(f"\n=== DIFFERENCES ===")
# Sheet stores fees as negative, Python stores positive (subtracted in net profit)
sheet_fees = 61234.37
sheet_hedge = -26644.42
sheet_farm = 10794.66
sheet_payout = 145295.20
sheet_net = 68211.07

print(f"  Challenge Fees:  diff = ${cf['challenge_fees'] - sheet_fees:,.2f}")
print(f"  Hedging Results: diff = ${cf['hedging_results'] - sheet_hedge:,.2f}")
print(f"  Farming Results: diff = ${cf['farming_results'] - sheet_farm:,.2f}")
print(f"  Payouts:         diff = ${cf['payouts'] - sheet_payout:,.2f}")
print(f"  Net Profit:      diff = ${cf['net_profit'] - sheet_net:,.2f}")
