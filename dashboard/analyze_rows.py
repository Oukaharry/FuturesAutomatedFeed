"""Analyze why we're missing rows"""
import pandas as pd
import requests
from io import StringIO

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

response = requests.get(SHEET_URL)
df = pd.read_csv(StringIO(response.text), header=1)

print(f"Total rows in sheet: {len(df)}")

# Check Prop Firm column
prop_firm_col = df['Prop Firm']
print(f"\nProp Firm column stats:")
print(f"  Non-null: {prop_firm_col.notna().sum()}")
print(f"  Null/Empty: {prop_firm_col.isna().sum()}")

# Look at null Prop Firm rows
null_rows = df[df['Prop Firm'].isna()]
print(f"\nRows with empty Prop Firm: {len(null_rows)}")

# Check if they have data in other columns
if len(null_rows) > 0:
    print("\nSample of rows with empty Prop Firm:")
    cols_to_check = ['Fee', 'Status P1', 'Hedge Net', 'Payout 1']
    for col in cols_to_check:
        if col in null_rows.columns:
            non_empty = null_rows[col].notna().sum()
            print(f"  {col}: {non_empty} non-empty values")

# Check actual Prop Firm values
print("\n=== PROP FIRM VALUE COUNTS ===")
print(df['Prop Firm'].value_counts())
