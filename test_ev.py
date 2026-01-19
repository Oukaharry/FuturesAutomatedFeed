"""Test EV calculation matching the sheet formula"""
import sys
sys.path.insert(0, '.')
from config.settings import SHEET_URL
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

evals = fetch_evaluations(SHEET_URL)

# Test the updated calculate_statistics EV
stats = calculate_statistics(evals, None, None)
print("=== Updated calculate_statistics EV ===")
print(f'EV from stats: ${stats["expected_value"]:.2f}')
ev_tracking = stats["ev_tracking"]
print(f'EV tracking - Total Net: ${ev_tracking["total_net_ended"]:.2f}, Count: {ev_tracking["count_ended"]}')
print()

# Manual verification
sum_col_n = 0  # Failed P1: -Fee + P1 hedges
sum_col_aa = 0  # Funded ended: All hedges + payouts - fee - act_fee
count_n = 0
count_aa = 0

for ev in evals:
    status_p1 = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status', '')).strip()
    
    fee = parse_currency(ev.get('Fee', 0))
    act_fee = parse_currency(ev.get('Activation Fee', 0))
    p1_hedge = parse_currency(ev.get('Hedge Net', 0))
    funded_hedge = parse_currency(ev.get('Hedge Net.1', 0))
    payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))
    
    # Column N/O: Failed P1 only
    if status_p1 == 'Fail':
        col_n_val = -fee + p1_hedge
        sum_col_n += col_n_val
        count_n += 1
        
    # Column AA/AB: Completed or Failed funded  
    if status_funded in ['Completed', 'Fail']:
        col_aa_val = p1_hedge + funded_hedge + payouts - fee - act_fee
        sum_col_aa += col_aa_val
        count_aa += 1

print("=== Manual Verification ===")
print(f'Failed P1: Sum=${sum_col_n:.2f}, Count={count_n}')
print(f'Funded Ended: Sum=${sum_col_aa:.2f}, Count={count_aa}')
ev_manual = (sum_col_n + sum_col_aa) / (count_n + count_aa) if (count_n + count_aa) else 0
print(f'EV = ${ev_manual:.2f}')
