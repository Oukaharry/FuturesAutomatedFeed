"""Check raw CSV column structure (before fetch_evaluations filtering)."""
import requests, io
import pandas as pd

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
resp = requests.get(csv_url, timeout=30)

# Read raw, skip header detection
df_raw = pd.read_csv(io.StringIO(resp.text), header=None) 

# Show first 3 rows to see headers
print("=== RAW CSV FIRST 3 ROWS ===")
pd.set_option('display.max_columns', 40)
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 20)
print(df_raw.iloc[:3, :35].to_string())

# Find header row and show columns
for i in range(5):
    row = df_raw.iloc[i].astype(str)
    if row.str.contains('Prop Firm', case=False).any():
        print(f"\n=== HEADER AT ROW {i} ===")
        headers = df_raw.iloc[i].tolist()
        for j, h in enumerate(headers[:40]):
            if pd.notna(h) and str(h).strip():
                # Column letter
                letter = ''
                idx = j
                while idx >= 0:
                    letter = chr(65 + idx % 26) + letter
                    idx = idx // 26 - 1
                print(f"  {letter:3s} (idx {j:2d}): {h}")
        break
