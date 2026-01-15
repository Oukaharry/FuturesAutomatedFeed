"""Quick test to compare sheet data vs dashboard"""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, calculate_statistics

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1vtuGcTe8ys44wHCJGJr6VoImeh8q0beaKkZMt0hd3VU/edit?usp=sharing'

print("Fetching from Google Sheet...")
evals = fetch_evaluations(SHEET_URL)
print(f"Records: {len(evals)}")

stats = calculate_statistics(evals)

print("\n=== PROFITABILITY - COMPLETED ===")
prof = stats['profitability_completed']
print(f"Challenge Fees:  ${prof['challenge_fees']:,.2f}")
print(f"Hedging Results: ${prof['hedging_results']:,.2f}")
print(f"Farming Results: ${prof['farming_results']:,.2f}")
print(f"Payouts:         ${prof['payouts']:,.2f}")
print(f"Net Profit:      ${prof['net_profit']:,.2f}")

print("\n=== CASHFLOW - IN PROGRESS ===")
cash = stats['cashflow_inprogress']
print(f"Challenge Fees:  ${cash['challenge_fees']:,.2f}")
print(f"Hedging Results: ${cash['hedging_results']:,.2f}")
print(f"Farming Results: ${cash['farming_results']:,.2f}")
print(f"Payouts:         ${cash['payouts']:,.2f}")
print(f"Net Profit:      ${cash['net_profit']:,.2f}")

print("\n=== EVAL TOTALS ===")
et = stats['eval_totals']
print(f"Running: {et['total_running']}")
print(f"Passed:  {et['total_passed']}")
print(f"Failed:  {et['total_failed']}")
print(f"Funded Rate: {et['funded_rate']:.1f}%")

print("\n=== FUNDED TOTALS ===")
ft = stats['funded_totals']
print(f"Not Started: {ft['not_started']}")
print(f"Ongoing:     {ft['ongoing']}")
print(f"Failed:      {ft['failed']}")
print(f"Completed:   {ft['completed']}")

print("\n=== EXPECTED VALUES FROM DASHBOARD ===")
print("(From your screenshots)")
print("PROFITABILITY - COMPLETED:")
print("  Challenge Fees:  $31,673.26")
print("  Hedging Results: $33,102.46")
print("  Farming Results: $6,626.80")
print("  Payouts:         $46,041.80")
print("  Net Profit:      $54,097.80")
print("\nCASHFLOW - IN PROGRESS:")
print("  Challenge Fees:  $2,665.94")
print("  Hedging Results: $0.00")
print("  Farming Results: -$292.00")
print("  Payouts:         $37,810.05")
print("  Net Profit:      $34,852.11")
print("\nEVAL TOTALS:")
print("  Running: 22, Passed: 115, Failed: 189")
print("\nFUNDED TOTALS:")
print("  Not Started: 6, Ongoing: 16, Failed: 76, Completed: 24")
