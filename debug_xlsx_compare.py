"""Compare XLSX vs CSV for Tyler's hedging and payout columns. Properly handle XLSX header."""
import requests, io, sys, json, sqlite3
import pandas as pd
from decimal import Decimal

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"
sys.path.insert(0, '.')
from utils.data_processor import parse_currency

# 1) Fetch fresh CSV (this is what our code uses)
print("Fetching CSV...")
csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
csv_resp = requests.get(csv_url, timeout=30)
csv_df = pd.read_csv(io.StringIO(csv_resp.text))
print(f"CSV rows: {len(csv_df)}, cols: {len(csv_df.columns)}")
print(f"CSV headers: {list(csv_df.columns[:15])}")

# 2) Fetch XLSX and find header row
print("\nFetching XLSX...")
xlsx_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
xlsx_resp = requests.get(xlsx_url, timeout=60)
xls = pd.ExcelFile(io.BytesIO(xlsx_resp.content))

# Read without header first to find header row
raw = pd.read_excel(xls, 'Evaluations', header=None)
print(f"XLSX raw rows: {len(raw)}")

# Find the header row - look for "Prop Firm" or "Fee" text
header_row = None
for i in range(min(10, len(raw))):
    row_vals = [str(v) for v in raw.iloc[i] if pd.notna(v)]
    if 'Fee' in row_vals or 'Prop Firm' in row_vals:
        header_row = i
        print(f"Found header at row {i}: {row_vals[:10]}")
        break

if header_row is not None:
    xlsx_df = pd.read_excel(xls, 'Evaluations', header=header_row)
    print(f"XLSX data rows: {len(xlsx_df)}")
    print(f"XLSX headers: {list(xlsx_df.columns[:15])}")
else:
    print("Could not find header row!")
    # Just use the raw data 
    xlsx_df = raw
    print(f"Using raw. First row: {[str(v) for v in raw.iloc[0] if pd.notna(v)]}")

# 3) Now compare column-by-column sums 
# Map CSV column names to positions
csv_cols = list(csv_df.columns)
xlsx_cols = list(xlsx_df.columns)

# Hedge columns by name
hedge_names = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5',
               'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
               'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
payout_names = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']

print(f"\n=== HEDGE COLUMN SUMS: CSV vs XLSX ===")
csv_hedge_total = Decimal('0')
xlsx_hedge_total = Decimal('0')

for col in hedge_names:
    csv_sum = Decimal('0')
    xlsx_sum = Decimal('0')
    
    # CSV sum
    if col in csv_df.columns:
        for val in csv_df[col]:
            csv_sum += Decimal(str(parse_currency(val)))
    
    # XLSX sum - try exact name match first, then fuzzy
    xlsx_col = None
    if col in xlsx_df.columns:
        xlsx_col = col
    else:
        # Try to find matching column
        for c in xlsx_df.columns:
            if str(c) == col:
                xlsx_col = c
                break
    
    if xlsx_col is not None:
        for val in xlsx_df[xlsx_col]:
            if pd.notna(val):
                try:
                    xlsx_sum += Decimal(str(round(float(val), 2)))
                except:
                    pass
    
    diff = csv_sum - xlsx_sum
    marker = " ***" if abs(diff) > Decimal('0.001') else ""
    print(f"  {col:25s}: CSV={csv_sum:>12}, XLSX={xlsx_sum:>12}, diff={diff:>8}{marker}")
    csv_hedge_total += csv_sum
    xlsx_hedge_total += xlsx_sum

print(f"  {'TOTAL':25s}: CSV={csv_hedge_total:>12}, XLSX={xlsx_hedge_total:>12}, diff={csv_hedge_total-xlsx_hedge_total:>8}")
print(f"  Stats tab value: -26644.42")

print(f"\n=== PAYOUT COLUMN SUMS: CSV vs XLSX ===")
csv_payout_total = Decimal('0')
xlsx_payout_total = Decimal('0')

for col in payout_names:
    csv_sum = Decimal('0')
    xlsx_sum = Decimal('0')
    
    if col in csv_df.columns:
        for val in csv_df[col]:
            csv_sum += Decimal(str(parse_currency(val)))
    
    xlsx_col = None
    if col in xlsx_df.columns:
        xlsx_col = col
    else:
        for c in xlsx_df.columns:
            if str(c) == col:
                xlsx_col = c
                break
    
    if xlsx_col is not None:
        for val in xlsx_df[xlsx_col]:
            if pd.notna(val):
                try:
                    xlsx_sum += Decimal(str(round(float(val), 2)))
                except:
                    pass
    
    diff = csv_sum - xlsx_sum
    marker = " ***" if abs(diff) > Decimal('0.001') else ""
    print(f"  {col:15s}: CSV={csv_sum:>12}, XLSX={xlsx_sum:>12}, diff={diff:>8}{marker}")
    csv_payout_total += csv_sum
    xlsx_payout_total += xlsx_sum

print(f"  {'TOTAL':15s}: CSV={csv_payout_total:>12}, XLSX={xlsx_payout_total:>12}, diff={csv_payout_total-xlsx_payout_total:>8}")
print(f"  Stats tab value: 145295.20")

# If CSV and XLSX match but both differ from Stats, check if ANY cells in the XLSX 
# have values that differ from what round(float, 2) gives (i.e., precision > 2 decimals)
print(f"\n=== XLSX CELLS WITH >2 DECIMAL PRECISION ===")
for col in hedge_names + payout_names:
    if col in xlsx_df.columns:
        for idx, val in xlsx_df[col].items():
            if pd.notna(val):
                try:
                    fval = float(val)
                    if abs(fval - round(fval, 2)) > 1e-10:
                        print(f"  Row {idx}, {col}: {val} (rounded: {round(fval,2)})")
                except:
                    pass
