"""
Inspect the RAW CSV from Joe's sheet BEFORE column filtering.
Check why the sheet shows $100K payouts but we see $0.
"""
import sys, requests, re
sys.path.insert(0, '.')

import pandas as pd
from io import StringIO
from utils.data_processor import parse_currency

SHEET_KEY = "1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4"

print("=== RAW CSV COLUMN NAMES ===")
csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv&gid=0"
resp = requests.get(csv_url, timeout=30)
raw_text = resp.text

# Find header row
lines = raw_text.split('\n')
for i, line in enumerate(lines[:15]):
    if 'Prop Firm' in line or 'Account Size' in line or 'Status' in line:
        print(f"Potential header at line {i}: {line[:200]}")

# Read with header detection
df_raw = pd.read_csv(StringIO(raw_text), header=None)
print(f"\nTotal rows (raw): {len(df_raw)}")
print(f"Total cols: {len(df_raw.columns)}")

# Find header row
header_idx = -1
for i, row in df_raw.head(10).iterrows():
    row_str = row.astype(str)
    if row_str.str.contains('Prop Firm', case=False, na=False).any():
        header_idx = i
        break

print(f"Header at row index: {header_idx}")

# Read with proper header
df = pd.read_csv(StringIO(raw_text), header=header_idx)
print(f"\nColumn names ({len(df.columns)} total):")
for i, col in enumerate(df.columns):
    print(f"  [{i:3d}] {col}")

# Find data rows (non-empty Prop Firm)
if 'Prop Firm' in df.columns:
    df = df[df['Prop Firm'].notna() & (df['Prop Firm'] != '')]

print(f"\nData rows: {len(df)}")

# Check Status column values
status_col = None
for col in df.columns:
    if col.strip().lower() == 'status' and 'p1' not in col.lower():
        status_col = col
        break

if status_col:
    print(f"\nStatus column: '{status_col}'")
    print(f"Status value counts:")
    vc = df[status_col].value_counts(dropna=False)
    for val, cnt in vc.items():
        print(f"  '{val}': {cnt}")

# Check Status P1 column
status_p1_col = None
for col in df.columns:
    if 'status' in col.lower() and 'p1' in col.lower():
        status_p1_col = col
        break

if status_p1_col:
    print(f"\nStatus P1 column: '{status_p1_col}'")
    vc = df[status_p1_col].value_counts(dropna=False)
    for val, cnt in vc.items():
        print(f"  '{val}': {cnt}")

# Check payouts
print("\n=== PAYOUT ANALYSIS ===")
payout_cols_found = [c for c in df.columns if 'payout' in c.lower() or 'Payout' in c]
print(f"Payout columns: {payout_cols_found}")

total_payouts = 0.0
rows_with_payouts = 0
for _, row in df.iterrows():
    row_payout = 0.0
    for col in payout_cols_found:
        row_payout += parse_currency(row.get(col))
    if abs(row_payout) > 0.01:
        rows_with_payouts += 1
        total_payouts += row_payout
        sp1 = str(row.get(status_p1_col or 'Status P1', '')).strip()
        sf  = str(row.get(status_col or 'Status', '')).strip()
        print(f"  Row with payout ${row_payout:.2f}: P1={sp1}, Status={sf}")

print(f"\nTotal payouts (raw): ${total_payouts:,.2f}")
print(f"Rows with payouts:   {rows_with_payouts}")

# Check farming / Hedge Day columns
print()
print("=== FARMING / HEDGE DAY ANALYSIS ===")
hedge_day_cols = [c for c in df.columns if 'Hedge Day' in c or 'hedge day' in c.lower()]
print(f"Hedge Day columns found: {len(hedge_day_cols)}")
total_farming = 0.0
rows_with_farming = 0
for _, row in df.iterrows():
    row_farm = sum(parse_currency(row.get(c)) for c in hedge_day_cols)
    if abs(row_farm) > 0.01:
        rows_with_farming += 1
        total_farming += row_farm
        sp1 = str(row.get(status_p1_col or 'Status P1', '')).strip()
        sf  = str(row.get(status_col or 'Status', '')).strip()
        if rows_with_farming <= 20:
            print(f"  Row farming=${row_farm:.2f}: P1={sp1}, Status={sf}")

print(f"\nTotal farming (raw): ${total_farming:,.2f}")
print(f"Rows with farming:   {rows_with_farming}")

# Summary for comparison
print()
print("=== SUMMARY ===")
print(f"If Status col works correctly, payouts for Status=Completed/Fail rows = ${total_payouts:.2f}")
print(f"Sheet Stats tab shows: Payouts=$100,189.00, Farming=$15,034.28")
print(f"Our code shows:        Payouts=$0.00,        Farming=$0.00")
print()
print("The difference is whether rows with payouts have Status=Completed|Fail or not.")
