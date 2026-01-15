"""Check Payout column locations"""
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

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Find Payout columns
print("Columns containing 'payout' or 'Payout':")
for i, col in enumerate(df.columns):
    if 'payout' in col.lower():
        print(f"  Index {i}: {col}")

# Check columns 27, 29, 31, 33 (AB, AD, AF, AH)
print("\nColumns at indices 27, 28, 29, 30, 31, 32, 33:")
for i in range(27, 34):
    if i < len(df.columns):
        print(f"  Index {i}: {df.columns[i]}")

# Sum all Payout columns for ended accounts
status_col = df.columns[19]
funded_ended = df[(df[status_col] == 'Fail') | (df[status_col] == 'Completed')]

payout_cols = [c for c in df.columns if 'payout' in c.lower()]
print(f"\nPayout columns found: {payout_cols}")

total_payouts = 0
for col in payout_cols:
    col_sum = funded_ended[col].apply(parse_currency).sum()
    print(f"  {col}: ${col_sum:.2f}")
    total_payouts += col_sum

print(f"\nTotal Payouts for ended accounts: ${total_payouts:.2f}")
print(f"Expected: $43,023.63")
