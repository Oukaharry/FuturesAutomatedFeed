"""Resync Ed's stats in the DB using the fixed calculate_statistics."""
import sys, json
sys.path.insert(0, '.')
from dashboard.database import get_connection, get_all_clients
from utils.data_processor import calculate_statistics
from datetime import datetime

all_clients = get_all_clients()
ed_id = next((cid for cid in all_clients if 'ed' in str(cid).lower()), None)
if not ed_id:
    ed_id = next((cid for cid in all_clients if 'ed' in str(all_clients[cid].get('identity', {}).get('name', '')).lower()), None)

print(f"Client ID: {ed_id}")
ed_data = all_clients[ed_id]
evals = ed_data.get('evaluations', [])

new_stats = calculate_statistics(evals, None, None)

ci = new_stats['cashflow_inprogress']
print(f"\ncashflow_inprogress after fix:")
print(f"  challenge_fees: ${ci['challenge_fees']:,.2f}  (sheet: $100,687.80)")
print(f"  hedging_results: ${ci['hedging_results']:,.2f}  (sheet: $119,445.37)")
print(f"  farming_results: ${ci['farming_results']:,.2f}  (sheet: -$229.04)")
print(f"  payouts: ${ci['payouts']:,.2f}  (sheet: $48,568.78)")
print(f"  net_profit: ${ci['net_profit']:,.2f}  (sheet: $67,098.17)")

with get_connection() as conn:
    conn.execute(
        'UPDATE clients_data SET statistics = ?, last_updated = ? WHERE client_id = ?',
        (json.dumps(new_stats), datetime.now().isoformat(), ed_id)
    )
    conn.commit()
print(f"\nDB updated for client '{ed_id}'")
