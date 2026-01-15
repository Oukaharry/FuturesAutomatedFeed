"""Test updated formulas"""
import sys
sys.path.insert(0, '..')
from utils.data_processor import fetch_evaluations, calculate_statistics

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/edit'

print("Fetching data...")
evals = fetch_evaluations(SHEET_URL)
print(f"Records: {len(evals)}")

stats = calculate_statistics(evals)

print("\n=== PROFITABILITY - COMPLETED ===")
p = stats['profitability_completed']
print(f"Challenge Fees:  ${p['challenge_fees']:,.2f}  (expected: $35,528.18)")
print(f"Hedging Results: ${p['hedging_results']:,.2f}  (expected: $10,309.60)")
print(f"Farming Results: ${p['farming_results']:,.2f}  (expected: $582.72)")
print(f"Payouts:         ${p['payouts']:,.2f}  (expected: $43,023.63)")
print(f"Net Profit:      ${p['net_profit']:,.2f}  (expected: $20,380.90)")

print("\n=== CASHFLOW - IN PROGRESS ===")
c = stats['cashflow_inprogress']
print(f"Challenge Fees:  ${c['challenge_fees']:,.2f}  (expected: $38,441.23)")
print(f"Hedging Results: ${c['hedging_results']:,.2f}  (expected: -$33,469.18)")
print(f"Farming Results: ${c['farming_results']:,.2f}  (expected: $6,604.17)")
print(f"Payouts:         ${c['payouts']:,.2f}  (expected: $69,459.76)")
print(f"Net Profit:      ${c['net_profit']:,.2f}  (expected: $6,146.65)")
