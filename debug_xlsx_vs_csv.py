"""Compare XLSX Evaluations data with stored CSV data to find where hedging/payout values diverge."""
import requests, io, sys, json, sqlite3
import pandas as pd
from decimal import Decimal

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

sys.path.insert(0, '.')
from utils.data_processor import parse_currency

# 1) Get XLSX Evaluations tab
print("Fetching XLSX...")
xlsx_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
resp = requests.get(xlsx_url, timeout=60)
xls = pd.ExcelFile(io.BytesIO(resp.content))
xlsx_df = pd.read_excel(xls, 'Evaluations')
print(f"XLSX rows: {len(xlsx_df)}")

# 2) Get stored evaluations (from CSV parse)
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()
evals = json.loads(data['evaluations'])
print(f"Stored eval rows: {len(evals)}")

# Column positions for hedging: I:M (8-12) and T:Z (19-25)
# Column positions for payouts: AB(27), AD(29), AF(31), AH(33)
hedge_cols_idx = list(range(8, 13)) + list(range(19, 26))
payout_cols_idx = [27, 29, 31, 33]

# Get XLSX column names by position
xlsx_cols = list(xlsx_df.columns)
print(f"\nXLSX hedge columns: {[xlsx_cols[i] for i in hedge_cols_idx if i < len(xlsx_cols)]}")
print(f"XLSX payout columns: {[xlsx_cols[i] for i in payout_cols_idx if i < len(xlsx_cols)]}")

# Compare sums: XLSX raw values vs stored CSV-parsed values
print("\n=== XLSX SUMS (raw numeric values from XLSX) ===")
xlsx_hedge_sum = Decimal('0')
for ci in hedge_cols_idx:
    col = xlsx_cols[ci]
    col_sum = Decimal('0')
    for idx, val in xlsx_df[col].items():
        if pd.notna(val):
            try:
                col_sum += Decimal(str(round(float(val), 2)))
            except:
                pass
    xlsx_hedge_sum += col_sum
print(f"XLSX hedge total: {xlsx_hedge_sum}")

xlsx_payout_sum = Decimal('0')
for ci in payout_cols_idx:
    col = xlsx_cols[ci]
    col_sum = Decimal('0')
    for idx, val in xlsx_df[col].items():
        if pd.notna(val):
            try:
                col_sum += Decimal(str(round(float(val), 2)))
            except:
                pass
    xlsx_payout_sum += col_sum
print(f"XLSX payout total: {xlsx_payout_sum}")

# Compare with stored data sums
stored_cols = list(evals[0].keys())
hedge_col_names = [stored_cols[i] for i in hedge_cols_idx if i < len(stored_cols)]
payout_col_names = [stored_cols[i] for i in payout_cols_idx if i < len(stored_cols)]

print(f"\n=== STORED CSV-PARSED SUMS ===")
stored_hedge_sum = Decimal('0')
for c in hedge_col_names:
    for ev in evals:
        stored_hedge_sum += Decimal(str(parse_currency(ev.get(c))))
print(f"Stored hedge total: {stored_hedge_sum}")

stored_payout_sum = Decimal('0')
for c in payout_col_names:
    for ev in evals:
        stored_payout_sum += Decimal(str(parse_currency(ev.get(c))))
print(f"Stored payout total: {stored_payout_sum}")

# Find row-level differences
print(f"\n=== ROW-LEVEL DIFFERENCES (XLSX vs Stored) ===")
min_rows = min(len(xlsx_df), len(evals))
found_diffs = 0

for row in range(min_rows):
    # Check hedge columns
    for ci in hedge_cols_idx:
        xlsx_col = xlsx_cols[ci]
        stored_col = stored_cols[ci]
        
        xlsx_val = xlsx_df.iloc[row][xlsx_col]
        xlsx_num = round(float(xlsx_val), 2) if pd.notna(xlsx_val) else 0.0
        
        stored_raw = evals[row].get(stored_col)
        stored_num = parse_currency(stored_raw)
        
        if abs(xlsx_num - stored_num) > 0.001:
            found_diffs += 1
            if found_diffs <= 30:
                print(f"  Row {row}, {stored_col}: XLSX={xlsx_num}, Stored={stored_num}, raw='{stored_raw}', diff={xlsx_num-stored_num:.4f}")
    
    # Check payout columns
    for ci in payout_cols_idx:
        xlsx_col = xlsx_cols[ci]
        stored_col = stored_cols[ci]
        
        xlsx_val = xlsx_df.iloc[row][xlsx_col]
        xlsx_num = round(float(xlsx_val), 2) if pd.notna(xlsx_val) else 0.0
        
        stored_raw = evals[row].get(stored_col)
        stored_num = parse_currency(stored_raw)
        
        if abs(xlsx_num - stored_num) > 0.001:
            found_diffs += 1
            if found_diffs <= 30:
                print(f"  Row {row}, {stored_col}: XLSX={xlsx_num}, Stored={stored_num}, raw='{stored_raw}', diff={xlsx_num-stored_num:.4f}")

print(f"\nTotal differing cells: {found_diffs}")
