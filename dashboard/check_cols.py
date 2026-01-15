"""Check column mappings for Hedge Days"""
import pandas as pd
import requests
from io import StringIO

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Print columns around the Hedge Day section
print("Columns 35-45:")
for i in range(35, min(45, len(df.columns))):
    print(f"  Column {i}: {df.columns[i]}")

print("\n--- Checking Hedge Day columns by name ---")
hedge_day_cols = [c for c in df.columns if 'hedge day' in c.lower()]
print(f"Found {len(hedge_day_cols)} Hedge Day columns:")
for c in hedge_day_cols[:10]:
    print(f"  {c}")

# The sheet formula uses columns: AM, AO, AQ, AS, AU, AW, AY, BA, BC, BE, BG, BI, BK, BM, BO, BQ, BS, BU, BW, BY, CA, CC, CE, CG, CI, CK, CM, CO, CQ, CS, CU, CW, CY, DA
# Convert to 0-based indices: AM=38, AN=39, AO=40, etc.
# A=0, B=1, ..., Z=25, AA=26, AB=27, ..., AM=38, AO=40, etc.

def col_letter_to_index(col):
    """Convert column letter to 0-based index"""
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1  # 0-based

formula_cols = ['AM', 'AO', 'AQ', 'AS', 'AU', 'AW', 'AY', 'BA', 'BC', 'BE', 'BG', 'BI', 'BK', 'BM', 'BO', 'BQ', 'BS', 'BU', 'BW', 'BY', 'CA', 'CC', 'CE', 'CG', 'CI', 'CK', 'CM', 'CO', 'CQ', 'CS', 'CU', 'CW', 'CY', 'DA']

print(f"\n--- Checking {len(formula_cols)} columns from Farming formula ---")
for col_letter in formula_cols[:5]:
    idx = col_letter_to_index(col_letter)
    col_name = df.columns[idx] if idx < len(df.columns) else "OUT OF RANGE"
    print(f"  {col_letter} (index {idx}): {col_name}")

print("...")

for col_letter in formula_cols[-3:]:
    idx = col_letter_to_index(col_letter)
    col_name = df.columns[idx] if idx < len(df.columns) else "OUT OF RANGE"
    print(f"  {col_letter} (index {idx}): {col_name}")

# Now calculate farming using EXACT column indices from formula
print("\n--- Calculating Farming Results using EXACT formula columns ---")
formula_indices = [col_letter_to_index(c) for c in formula_cols]
print(f"Formula column indices: {formula_indices[:5]}...{formula_indices[-3:]}")

# Status column (T = index 19)
status_col = df.columns[19]  # T = Status
print(f"Status column (T, index 19): {status_col}")

# Sum hedge days where Status = "Completed"
farming_completed = 0
completed_rows = df[df[status_col].str.strip().str.lower() == 'completed'] if pd.api.types.is_string_dtype(df[status_col]) else df[df[status_col] == 'Completed']

print(f"Found {len(completed_rows)} rows with Status=Completed")

for idx in formula_indices:
    if idx < len(df.columns):
        col = df.columns[idx]
        col_sum = pd.to_numeric(completed_rows.iloc[:, idx], errors='coerce').fillna(0).sum()
        farming_completed += col_sum
        if col_sum != 0:
            print(f"  Column {idx} ({col[:20]}): ${col_sum:.2f}")

print(f"\nTotal Farming Results Completed: ${farming_completed:.2f}")
print(f"Expected: $582.72")
