"""Broad scan for comma-containing values in hedge columns"""
import sys, requests, io
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'
url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
df = pd.read_csv(io.StringIO(r.text), header=1, dtype=str)
df.columns = [str(c).strip() for c in df.columns]
df = df[df['Prop Firm'].notna() & ~df['Prop Firm'].astype(str).str.strip().isin(['', 'nan'])].copy()

hedge_cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5',
              'Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
              'Hedge Result 5.1','Hedge Result 6','Hedge Result 7',
              'Fee', 'Activation Fee', 'Farming Net', 'Hedge Net', 'Hedge Net.1',
              'Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']

print('Scanning all financial columns for unusual comma patterns...')
found = 0
for col in hedge_cols:
    if col not in df.columns:
        continue
    for idx, val in df[col].items():
        s = str(val).strip()
        if s in ('', 'nan'):
            continue
        # Flag: has a comma but no dollar sign AND no period
        has_comma = ',' in s
        has_dollar = '$' in s
        has_period = '.' in s
        if has_comma and not has_dollar and not has_period:
            firm = str(df.at[idx, 'Prop Firm'])
            status = str(df.at[idx, 'Status']) if 'Status' in df.columns else '?'
            print(f"  col={col:22s} idx={idx:4d} val={s!r:15s}  {firm}  {status}")
            found += 1

print(f'\nTotal suspicious values (comma, no $, no .): {found}')

# Also check: values with both comma and period but period not at the end
for col in ['Hedge Result 2.1', 'Hedge Result 3.1']:
    if col not in df.columns:
        continue
    print(f'\nAll non-blank values in {col} (sample of 10 largest magnitude):')
    def pf(v):
        try:
            return float(str(v).replace('$','').replace(',','').strip())
        except:
            return 0.0
    df['_tmp'] = df[col].apply(pf)
    top = df.nsmallest(5, '_tmp')
    for _, row in top.iterrows():
        print(f"  raw={row[col]!r:15s}  parsed={row['_tmp']:>10,.2f}  {row['Prop Firm']}  {row.get('Status','?')}")
