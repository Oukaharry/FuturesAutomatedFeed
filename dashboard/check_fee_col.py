"""Check Fee column contents"""
import pandas as pd
import requests
from io import StringIO

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Check Fee column
fee_col = df.columns[3]
print(f"Column D name: '{fee_col}'")
print(f"\nFirst 10 Fee values:")
print(df[fee_col].head(10))

print(f"\nFee column data type: {df[fee_col].dtype}")
print(f"\nUnique Fee values (first 20):")
print(df[fee_col].unique()[:20])

# Try parsing as currency
def parse_currency(val):
    if pd.isna(val) or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '').replace('$', '').replace(' ', ''))
    except:
        return 0.0

parsed_fees = df[fee_col].apply(parse_currency)
print(f"\nParsed Fee sum: ${parsed_fees.sum():.2f}")

# Filter for ended accounts
status_p1_col = df.columns[7]
status_col = df.columns[19]

ended_rows = df[(df[status_p1_col] == 'Fail') | (df[status_col] == 'Fail') | (df[status_col] == 'Completed')]
print(f"\nEnded rows: {len(ended_rows)}")
ended_fees = ended_rows[fee_col].apply(parse_currency).sum()
print(f"Challenge Fees Completed: ${ended_fees:.2f}")
