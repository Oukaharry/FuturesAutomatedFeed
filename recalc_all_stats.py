"""Recalculate and save statistics for ALL clients."""
import sys; sys.path.insert(0, '.')
from dashboard.database import get_all_clients, save_client_data
from utils.data_processor import calculate_statistics

all_clients = get_all_clients()
print(f"Recalculating stats for {len(all_clients)} clients...\n")

for cid, data in all_clients.items():
    evals = data.get('evaluations', [])
    old_pc = data.get('statistics', {}).get('profitability_completed', {})
    old_fees = old_pc.get('challenge_fees', 0)

    new_stats = calculate_statistics(evals)
    new_fees = new_stats.get('profitability_completed', {}).get('challenge_fees', 0)

    diff = new_fees - old_fees
    flag = f"  ← UPDATED (+{diff:.2f})" if abs(diff) > 0.01 else "  ✓"
    print(f"  {str(cid):<20} fees: {old_fees:>12.2f} → {new_fees:>12.2f}{flag}")

    save_client_data(cid, {'statistics': new_stats})

print("\nDone.")
