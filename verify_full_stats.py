"""
Run full calculate_statistics against Nikki's live sheet with fix applied.
Compare to Stats tab expected values.
"""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, calculate_statistics

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

print("Fetching Nikki evaluations...")
evals, _ = fetch_evaluations(f'https://docs.google.com/spreadsheets/d/{KEY}/edit')
print(f"  {len(evals)} rows fetched")

print("\nCalculating statistics...")
stats = calculate_statistics(evals)

pc = stats["profitability_completed"]
ci = stats["cashflow_inprogress"]

print("\n=== Profitability - Completed ===")
print(f"  Fees:     {-pc['challenge_fees']:>12,.2f}   (expect -52,431.47)")
print(f"  Hedging:  {pc['hedging_results']:>12,.2f}   (expect +10,288.06)")
print(f"  Farming:  {pc['farming_results']:>12,.2f}   (expect  +3,264.67)")
print(f"  Payouts:  {pc['payouts']:>12,.2f}   (expect +110,916.67)")

print("\n=== Cashflow - In Progress ===")
print(f"  Fees:     {-(ci['challenge_fees']):>12,.2f}   (expect -56,947.70)")
print(f"  Hedging:  {ci['hedging_results']:>12,.2f}   (expect -30,959.91)")
print(f"  Farming:  {ci['farming_results']:>12,.2f}   (expect  -5,368.01)")
print(f"  Payouts:  {ci['payouts']:>12,.2f}   (expect +135,715.60)")

print("\n=== Diffs ===")
print(f"  Completed Hedging diff: {pc['hedging_results'] - 10288.06:>+12,.2f}")
print(f"  InProgress Hedging diff: {ci['hedging_results'] - (-30959.91):>+12,.2f}")
print(f"  Fees diff: {-pc['challenge_fees'] - (-52431.47):>+12,.2f}")
print(f"  Payouts diff: {pc['payouts'] - 110916.67:>+12,.2f}")
