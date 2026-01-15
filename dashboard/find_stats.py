"""Look for Stats data in the sheet"""
import pandas as pd
import requests
from io import StringIO

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

response = requests.get(SHEET_URL)

# Read raw without any header processing
df_raw = pd.read_csv(StringIO(response.text), header=None)

print(f"Total rows in raw CSV: {len(df_raw)}")
print(f"Total columns in raw CSV: {len(df_raw.columns)}")

# Look for "Profitability" text anywhere
print("\n=== SEARCHING FOR 'Profitability' ===")
for i, row in df_raw.iterrows():
    for j, val in enumerate(row):
        if pd.notna(val) and 'Profitability' in str(val):
            print(f"Found at row {i}, col {j}: {val}")

# Look for specific values from screenshot
print("\n=== SEARCHING FOR '$35,528.18' ===")
for i, row in df_raw.iterrows():
    for j, val in enumerate(row):
        if pd.notna(val) and '35,528' in str(val):
            print(f"Found at row {i}, col {j}: {val}")

print("\n=== SEARCHING FOR '$10,309' (Hedge from screenshot) ===")
for i, row in df_raw.iterrows():
    for j, val in enumerate(row):
        if pd.notna(val) and '10,309' in str(val):
            print(f"Found at row {i}, col {j}: {val}")

print("\n=== SEARCHING FOR '$20,380' (Net Profit from screenshot) ===")
for i, row in df_raw.iterrows():
    for j, val in enumerate(row):
        if pd.notna(val) and '20,380' in str(val):
            print(f"Found at row {i}, col {j}: {val}")

# Print the first few rows of all data
print("\n=== FIRST 5 ROWS RAW ===")
for i in range(min(5, len(df_raw))):
    non_empty = [(j, v) for j, v in enumerate(df_raw.iloc[i]) if pd.notna(v) and str(v).strip()]
    print(f"Row {i}: {non_empty[:10]}")
