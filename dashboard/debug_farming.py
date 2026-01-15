"""Debug farming with exact match"""
import pandas as pd
import requests
from io import StringIO

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Column T (index 19) = Status
status_col = df.columns[19]
print(f"Column T (19): {status_col}")

# Check unique values in Status column
print("\nUnique Status values:")
print(df[status_col].value_counts(dropna=False))

# Count exact "Completed" matches
completed_mask = df[status_col] == "Completed"
print(f"\nRows with Status exactly = 'Completed': {completed_mask.sum()}")

# Maybe there's trailing spaces?
completed_mask2 = df[status_col].astype(str).str.strip() == "Completed"
print(f"Rows with Status.strip() = 'Completed': {completed_mask2.sum()}")

# The formula columns
def col_letter_to_index(col):
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1

formula_cols = ['AM', 'AO', 'AQ', 'AS', 'AU', 'AW', 'AY', 'BA', 'BC', 'BE', 'BG', 'BI', 'BK', 'BM', 'BO', 'BQ', 'BS', 'BU', 'BW', 'BY', 'CA', 'CC', 'CE', 'CG', 'CI', 'CK', 'CM', 'CO', 'CQ', 'CS', 'CU', 'CW', 'CY', 'DA']
formula_indices = [col_letter_to_index(c) for c in formula_cols]

# Calculate using exact "Completed" match
completed_rows = df[df[status_col] == "Completed"]
farming_completed = 0
for idx in formula_indices:
    if idx < len(df.columns):
        col_sum = pd.to_numeric(completed_rows.iloc[:, idx], errors='coerce').fillna(0).sum()
        farming_completed += col_sum

print(f"\nFarming Results (Status == 'Completed'): ${farming_completed:.2f}")
print(f"Expected: $582.72")

# Let me try summing column by column with SUMIF logic manually
print("\n--- Row-by-row check for Hedge Day 1 (AM) ---")
for i, row in df.iterrows():
    status_val = row[status_col]
    hedge_day_1 = pd.to_numeric(row.iloc[38], errors='coerce')
    if status_val == "Completed" and pd.notna(hedge_day_1) and hedge_day_1 != 0:
        print(f"Row {i}: Status={status_val}, Hedge Day 1={hedge_day_1}")
