"""
Find exactly which rows are causing the -57,125.04 discrepancy.
Check column deduplication, and look for rows with large HR2.1 or HR3.1 values.
"""
import sys, requests, io
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

def pf(v):
    try: return float(str(v).replace(',','').replace('$','').replace('(','').replace(')','').strip() or '0')
    except: return 0.0

# Fetch the CSV raw
url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=20, headers={'User-Agent':'Mozilla/5.0'})
raw = r.text

# Load with no header first to see raw rows
df_raw = pd.read_csv(io.StringIO(raw), header=None, nrows=3)
print("=== Rows 0,1,2 with col indices ===")
for i, row in df_raw.iterrows():
    print(f"Row {i}: {[(j, v) for j,v in enumerate(row) if str(v).strip() not in ('', 'nan')][:15]}")

# Now load the way fetch_evaluations does
df_full = pd.read_csv(io.StringIO(raw), header=None)
# Find header row
header_idx = -1
for i, row in df_full.head(10).iterrows():
    if row.astype(str).str.contains('Prop Firm', case=False, na=False).any():
        header_idx = i
        break
print(f"\nHeader row found at index: {header_idx}")

df = pd.read_csv(io.StringIO(raw), header=header_idx)
df.columns = [str(c).strip() for c in df.columns]

# Show the actual column names post-deduplication for key indices
print("\n=== Columns after pandas dedup (key indices) ===")
for i, col in enumerate(df.columns):
    if 'Hedge Result' in col or 'Status' in col:
        print(f"  col[{i:>3}] = {col!r}")

# Show all column names to see if Version shifted anything
print(f"\nTotal columns: {len(df.columns)}")
print("Columns 15-30:")
for i in range(15, min(31, len(df.columns))):
    print(f"  [{i:>3}] {df.columns[i]!r}")

# Filter to data rows
df2 = df[df['Prop Firm'].notna() & (df['Prop Firm'].astype(str).str.strip() != '')]

# Sum all funded hedge cols
fd_cols = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
           'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
p1_cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']

print(f"\n=== Available funded cols: {[c for c in fd_cols if c in df2.columns]} ===")
print(f"Missing funded cols: {[c for c in fd_cols if c not in df2.columns]}")

for col in fd_cols:
    if col in df2.columns:
        s = df2[col].apply(pf).sum()
        print(f"  SUM({col:25s}) = {s:>12,.2f}")

total_fd = sum(df2[c].apply(pf).sum() for c in fd_cols if c in df2.columns)
total_p1 = sum(df2[c].apply(pf).sum() for c in p1_cols if c in df2.columns)
print(f"\n  SUM(J:N)  = {total_p1:>12,.2f}")
print(f"  SUM(U:AA) = {total_fd:>12,.2f}")
print(f"  TOTAL     = {total_p1+total_fd:>12,.2f}  (expected: -30,959.91)")
print(f"  DIFF      = {total_p1+total_fd - (-30959.91):>+12,.2f}")

# Find rows with large HR2.1 or HR3.1
print("\n=== Top 10 rows by |HR2.1| ===")
if 'Hedge Result 2.1' in df2.columns:
    df2 = df2.copy()
    df2['_hr21'] = df2['Hedge Result 2.1'].apply(pf)
    top = df2.nlargest(5, '_hr21')[['Prop Firm','Account Size','Status','Hedge Result 2.1','_hr21']]
    print(top.to_string())
    print()
    bot = df2.nsmallest(5, '_hr21')[['Prop Firm','Account Size','Status','Hedge Result 2.1','_hr21']]
    print(bot.to_string())

print("\n=== Top 10 rows by |HR3.1| ===")
if 'Hedge Result 3.1' in df2.columns:
    df2['_hr31'] = df2['Hedge Result 3.1'].apply(pf)
    top = df2.nlargest(5, '_hr31')[['Prop Firm','Account Size','Status','Hedge Result 3.1','_hr31']]
    print(top.to_string())
    print()
    bot = df2.nsmallest(5, '_hr31')[['Prop Firm','Account Size','Status','Hedge Result 3.1','_hr31']]
    print(bot.to_string())
