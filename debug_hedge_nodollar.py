"""Find all non-standard (no dollar sign) hedge values"""
import sys, requests, io
sys.path.insert(0, '.')
import pandas as pd
from utils.data_processor import parse_currency

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'
url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
df = pd.read_csv(io.StringIO(r.text), header=1, dtype=str)
df.columns = [str(c).strip() for c in df.columns]
df = df[df['Prop Firm'].notna() & ~df['Prop Firm'].astype(str).str.strip().isin(['', 'nan'])].copy()

fdcols = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
          'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
p1cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']

print("ALL hedge values without a dollar sign (non-empty):")
no_dollar_total = 0.0
for col in p1cols + fdcols:
    if col not in df.columns:
        continue
    for idx, val in df[col].items():
        s = str(val).strip()
        if s in ('', 'nan'):
            continue
        if '$' not in s:
            parsed = parse_currency(s)
            status = str(df.at[idx, 'Status']) if 'Status' in df.columns else '?'
            firm = str(df.at[idx, 'Prop Firm'])
            print(f"  row={idx:4d}  col={col:22s}  raw={s!r:15s}  parsed={parsed:>10,.2f}  {firm}  {status}")
            no_dollar_total += parsed

print(f"\nTotal parsed value of no-dollar cells: {no_dollar_total:>12,.2f}")
print(f"Gap to close: -319.83")
print(f"Hint: if these cells are TEXT in sheet (→ 0 in SUM), we should also return 0")
