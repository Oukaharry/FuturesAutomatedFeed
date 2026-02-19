"""Check status column mappings"""
import pandas as pd
import requests
from io import StringIO

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
print(f"Status Code: {r.status_code}")
try:
    df = pd.read_csv(StringIO(r.text), header=1)
except Exception as e:
    print(f"Error reading CSV: {e}")
    exit()

print("Columns containing 'Status':")
status_cols = [c for c in df.columns if 'status' in str(c).lower()]
for c in status_cols:
    print(f"  '{c}'")

# Print unique values in these columns to see what "Failed" or "Completed" looks like
for c in status_cols:
    print(f"\nUnique values in '{c}':")
    try:
        print(df[c].unique())
    except:
        print("  (Could not print unique values)")
