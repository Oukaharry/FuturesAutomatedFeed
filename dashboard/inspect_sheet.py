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

# Search for the missing IDs ANYWHERE in the entire dataframe
missing_ids = ['74020', '74018', '80594', '66787', '74019', '32229', '32479', '53986', '74013', '98765']
print(f"\nSearching for missing IDs: {missing_ids}")

for search_id in missing_ids:
    # Convert all columns to string and search
    mask = df.astype(str).apply(lambda x: x.str.contains(search_id, case=False, na=False)).any(axis=1)
    if mask.any():
        print(f"\n✅ Found {search_id} in {mask.sum()} rows:")
        found_rows = df[mask]
        for idx, row in found_rows.iterrows():
            # Print which column contains it
            for col in df.columns:
                val = str(row[col])
                if search_id in val:
                    print(f"   Row {idx}: Column '{col}' = '{val}'")
    else:
        print(f"FAILED to find {search_id}")
