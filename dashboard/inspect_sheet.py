"""Inspect raw CSV columns from Tsubasa sheet"""
import pandas as pd
import requests
from io import StringIO

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

response = requests.get(SHEET_URL)
df = pd.read_csv(StringIO(response.text), header=None)

# Find header row
header_idx = -1
for i, row in df.head(10).iterrows():
    if row.astype(str).str.contains('Prop Firm').any():
        header_idx = i
        break

print(f"Header row index: {header_idx}")

# Reload with header
df = pd.read_csv(StringIO(response.text), header=header_idx)

print(f"\nTotal columns: {len(df.columns)}")
print(f"Total rows: {len(df)}")

print("\n=== ALL COLUMNS ===")
for i, col in enumerate(df.columns):
    print(f"  {i}: {col}")

# Check first 5 data rows for key columns
print("\n=== SAMPLE DATA ===")
key_cols = ['Prop Firm', 'Fee', 'Status P1', 'Status', 'Hedge Result 1', 'Hedge Net', 'Payout 1']
for col in key_cols:
    if col in df.columns:
        print(f"{col}: {df[col].head(3).tolist()}")
