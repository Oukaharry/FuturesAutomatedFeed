"""Verify that Stats tab extraction + override produces exact match."""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, calculate_statistics

SHEET_URL = "https://docs.google.com/spreadsheets/d/1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI/edit?gid=0#gid=0"

print("Fetching evaluations + XLSX notes (Stats tab)...")
result = fetch_evaluations(SHEET_URL)
if isinstance(result, tuple):
    evals, xlsx_notes = result
else:
    evals = result
    xlsx_notes = {}

print(f"Evaluations: {len(evals)} rows")
print(f"XLSX notes keys: {[k for k in xlsx_notes.keys() if isinstance(k, str)]}")

stats_tab = xlsx_notes.get('__stats_tab__', {})
print(f"Stats tab values: {stats_tab}")

# Calculate WITH Stats tab overrides
new_stats = calculate_statistics(evals, None, None, xlsx_notes=xlsx_notes)
cf = new_stats['cashflow_inprogress']
pc = new_stats['profitability_completed']

print(f"\n=== RECALCULATED (with Stats tab override) ===")
print(f"  Current Cashflow - In Progress:")
print(f"    Challenge Fees:   ${cf['challenge_fees']:,.2f}")
print(f"    Hedging Results:  ${cf['hedging_results']:,.2f}")
print(f"    Farming Results:  ${cf['farming_results']:,.2f}")
print(f"    Payouts:          ${cf['payouts']:,.2f}")
print(f"    Net Profit:       ${cf['net_profit']:,.2f}")

print(f"\n  Profitability - Completed:")
print(f"    Challenge Fees:   ${pc['challenge_fees']:,.2f}")
print(f"    Hedging Results:  ${pc['hedging_results']:,.2f}")
print(f"    Farming Results:  ${pc['farming_results']:,.2f}")
print(f"    Payouts:          ${pc['payouts']:,.2f}")
print(f"    Net Profit:       ${pc['net_profit']:,.2f}")

# Also calculate WITHOUT overrides for comparison
new_stats_no_override = calculate_statistics(evals, None, None)
cf2 = new_stats_no_override['cashflow_inprogress']

print(f"\n=== WITHOUT OVERRIDE (CSV-based) ===")
print(f"  Challenge Fees:   ${cf2['challenge_fees']:,.2f}")
print(f"  Hedging Results:  ${cf2['hedging_results']:,.2f}")
print(f"  Farming Results:  ${cf2['farming_results']:,.2f}")
print(f"  Payouts:          ${cf2['payouts']:,.2f}")
print(f"  Net Profit:       ${cf2['net_profit']:,.2f}")

print(f"\n=== GOOGLE SHEET STATS TAB (known values) ===")
print(f"  Challenge Fees:   -$61,234.37")
print(f"  Hedging Results:  -$26,644.42")
print(f"  Farming Results:   $10,794.66")
print(f"  Payouts:          $145,295.20")
print(f"  Net Profit:        $68,211.07")

print(f"\n=== DIFFERENCES (override vs sheet) ===")
expected = {'challenge_fees': 61234.37, 'hedging_results': -26644.42, 'farming_results': 10794.66, 'payouts': 145295.20, 'net_profit': 68211.07}
for key in expected:
    diff = cf[key] - expected[key]
    status = "MATCH" if abs(diff) < 0.01 else f"DIFF ${diff:,.2f}"
    print(f"  {key:20s}: {status}")
