import requests, io, pandas as pd

url = 'https://docs.google.com/spreadsheets/d/1JK1lCkfj8GRQEKD2AOILms8LZom3I5zQ-_UrQU9xw8o/export?format=csv'
r = requests.get(url, timeout=30)
df = pd.read_csv(io.StringIO(r.text), header=1)

print("=== ALL COLUMNS ===")
for i, c in enumerate(df.columns):
    # Show sample values for each column
    sample = df.iloc[:, i].dropna().head(3).tolist()
    sample_str = str(sample)[:80]
    print(f'  Col {i:3d}: [{c:30s}] samples: {sample_str}')

# Check the raw header row too - what does the original spreadsheet header look like?
df_raw = pd.read_csv(io.StringIO(r.text), header=None)
print("\n=== RAW HEADER ROW (row 1) ===")
header_vals = df_raw.iloc[1].tolist()
for i, v in enumerate(header_vals):
    if pd.notna(v) and str(v).strip():
        print(f'  Col {i:3d}: [{v}]')

# Also look at row 0 (might be a title row)
print("\n=== ROW 0 (title?) ===")
row0 = df_raw.iloc[0].tolist()
for i, v in enumerate(row0):
    if pd.notna(v) and str(v).strip():
        print(f'  Col {i:3d}: [{v}]')
