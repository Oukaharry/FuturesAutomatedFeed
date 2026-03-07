"""Recalculate and save Davy's statistics from current evaluations."""
import sys; sys.path.insert(0, '.')
from dashboard.database import get_all_clients, save_client_data, get_client_data
from utils.data_processor import calculate_statistics

all_clients = get_all_clients()
for cid, data in all_clients.items():
    if 'davy' in str(cid).lower():
        evals = data.get('evaluations', [])
        print(f"Client: {cid}, {len(evals)} evaluations")
        
        old_stats = data.get('statistics', {})
        old_pc = old_stats.get('profitability_completed', {})
        print(f"OLD stored challenge_fees: {old_pc.get('challenge_fees')}")

        new_stats = calculate_statistics(evals)
        new_pc = new_stats.get('profitability_completed', {})
        new_ci = new_stats.get('cashflow_inprogress', {})
        print(f"NEW calculated challenge_fees: {new_pc.get('challenge_fees')}")

        save_client_data(cid, {'statistics': new_stats})
        print("Saved.")

        # Verify
        saved = get_client_data(cid)
        s_pc = saved.get('statistics', {}).get('profitability_completed', {})
        s_ci = saved.get('statistics', {}).get('cashflow_inprogress', {})
        print(f"\n=== Verified stored stats ===")
        print("Profitability Completed:")
        for k, v in s_pc.items():
            print(f"  {k}: {v}")
        print("Cashflow InProgress:")
        for k, v in s_ci.items():
            print(f"  {k}: {v}")
        break
