"""Verify all calculations against sheet formulas"""
import pandas as pd
import requests
from io import StringIO

def parse_currency(val):
    if pd.isna(val) or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '').replace('$', '').replace(' ', ''))
    except:
        return 0.0

def col_letter_to_index(col):
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Column indices
# D=3 (Fee), H=7 (Status P1), T=19 (Status)
# J-N = 9-13 (Hedge Result 1-5 for Phase 1)
# U-AA = 20-26 (Hedge Result 1.1-7 for Funded)
# Hedge Days: AM, AO, AQ... = 38, 40, 42... (every other column)

status_p1_col = df.columns[7]  # H
status_col = df.columns[19]    # T
fee_col = df.columns[3]        # D

print("=== CHALLENGE FEES COMPLETED ===")
print("Formula: (SUMIF(Fee,P1='Fail') + SUMIF(Fee,Status='Completed') + SUMIF(Fee,Status='Fail')) * -1")
ended_rows = df[(df[status_p1_col] == 'Fail') | (df[status_col] == 'Fail') | (df[status_col] == 'Completed')]
challenge_fees = ended_rows[fee_col].apply(parse_currency).sum()
print(f"Result: ${challenge_fees:.2f} (expected: $35,528.18)")

print("\n=== HEDGING RESULTS COMPLETED ===")
# P1 hedges (J-N) where P1=Fail
# + Funded hedges (U-AA) where Status=Fail or Completed
# + P1 hedges (J-N) where Status=Fail or Completed
p1_fail_rows = df[df[status_p1_col] == 'Fail']
funded_ended_rows = df[(df[status_col] == 'Fail') | (df[status_col] == 'Completed')]

p1_hedge_cols = [9, 10, 11, 12, 13]  # J-N
funded_hedge_cols = [20, 21, 22, 23, 24, 25, 26]  # U-AA

hedging_part1 = sum(p1_fail_rows.iloc[:, col].apply(parse_currency).sum() for col in p1_hedge_cols)
hedging_part2 = sum(funded_ended_rows.iloc[:, col].apply(parse_currency).sum() for col in funded_hedge_cols)
hedging_part3 = sum(funded_ended_rows.iloc[:, col].apply(parse_currency).sum() for col in p1_hedge_cols)

hedging_results = hedging_part1 + hedging_part2 + hedging_part3
print(f"Part 1 (P1 hedges where P1=Fail): ${hedging_part1:.2f}")
print(f"Part 2 (Funded hedges where Status ended): ${hedging_part2:.2f}")
print(f"Part 3 (P1 hedges where Status ended): ${hedging_part3:.2f}")
print(f"Result: ${hedging_results:.2f} (expected: $10,309.60)")

print("\n=== FARMING RESULTS COMPLETED ===")
print("Formula: SUMIF(Hedge Days, Status='Completed')")
# Only Status='Completed' rows
completed_rows = df[df[status_col] == 'Completed']
print(f"Completed rows: {len(completed_rows)}")

# Hedge Day columns (AM, AO, AQ... = odd indices starting from 38)
hedge_day_cols = ['AM', 'AO', 'AQ', 'AS', 'AU', 'AW', 'AY', 'BA', 'BC', 'BE', 'BG', 'BI', 'BK', 'BM', 'BO', 'BQ', 'BS', 'BU', 'BW', 'BY', 'CA', 'CC', 'CE', 'CG', 'CI', 'CK', 'CM', 'CO', 'CQ', 'CS', 'CU', 'CW', 'CY', 'DA']
hedge_day_indices = [col_letter_to_index(c) for c in hedge_day_cols]

farming_total = 0
for idx in hedge_day_indices:
    if idx < len(df.columns):
        col_sum = completed_rows.iloc[:, idx].apply(parse_currency).sum()
        farming_total += col_sum

print(f"Result: ${farming_total:.2f} (expected: $582.72)")

print("\n=== PAYOUTS COMPLETED ===")
# Payouts where Status='Completed' or 'Fail'
payout_cols = [27, 29, 31, 33]  # AB, AD, AF, AH
payouts = sum(funded_ended_rows.iloc[:, col].apply(parse_currency).sum() for col in payout_cols if col < len(df.columns))
print(f"Result: ${payouts:.2f} (expected: $43,023.63)")

print("\n=== NET PROFIT COMPLETED ===")
# Fee is negative (expense), hedging/farming/payouts are income
net_profit = -challenge_fees + hedging_results + farming_total + payouts
print(f"Result: ${net_profit:.2f} (expected: $20,380.90)")
