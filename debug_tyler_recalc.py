"""Recalculate Tyler's statistics from stored evaluations and save to DB."""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import calculate_statistics

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT evaluations, account, deals FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()

evals = json.loads(data['evaluations']) if data['evaluations'] else []
mt5_account = json.loads(data['account']) if data['account'] else None
mt5_deals = json.loads(data['deals']) if data['deals'] else None

print(f"Evaluations: {len(evals)}, MT5 Account: {'Yes' if mt5_account else 'No'}, MT5 Deals: {len(mt5_deals) if mt5_deals else 0}")

# Recalculate
new_stats = calculate_statistics(evals, mt5_deals, mt5_account)

# Show before/after
cur.execute("SELECT statistics FROM clients_data WHERE client_id='Tyler'")
old_data = cur.fetchone()
old_stats = json.loads(old_data['statistics']) if old_data['statistics'] else {}

print(f"\n=== BEFORE (stored stats) ===")
cf_old = old_stats.get('cashflow_inprogress', {})
print(f"  Challenge Fees:   ${cf_old.get('challenge_fees', 0):,.2f}")
print(f"  Hedging Results:  ${cf_old.get('hedging_results', 0):,.2f}")
print(f"  Farming Results:  ${cf_old.get('farming_results', 0):,.2f}")
print(f"  Payouts:          ${cf_old.get('payouts', 0):,.2f}")
print(f"  Net Profit:       ${cf_old.get('net_profit', 0):,.2f}")

print(f"\n=== AFTER (recalculated) ===")
cf_new = new_stats.get('cashflow_inprogress', {})
print(f"  Challenge Fees:   ${cf_new.get('challenge_fees', 0):,.2f}")
print(f"  Hedging Results:  ${cf_new.get('hedging_results', 0):,.2f}")
print(f"  Farming Results:  ${cf_new.get('farming_results', 0):,.2f}")
print(f"  Payouts:          ${cf_new.get('payouts', 0):,.2f}")
print(f"  Net Profit:       ${cf_new.get('net_profit', 0):,.2f}")

# Save updated stats
cur.execute("UPDATE clients_data SET statistics = ? WHERE client_id = 'Tyler'", (json.dumps(new_stats),))
conn.commit()
conn.close()

print(f"\n✓ Tyler's statistics have been recalculated and saved to the database.")
