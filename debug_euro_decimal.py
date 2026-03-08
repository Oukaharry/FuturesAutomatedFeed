"""
Find ALL cells in hedge result columns where comma is used as decimal separator
(e.g., "-573,79" being parsed as -57379 instead of -573.79)
"""
import sys, requests, io, re
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=20, headers={'User-Agent':'Mozilla/5.0'})
df = pd.read_csv(io.StringIO(r.text), header=1, dtype=str)
df.columns = [str(c).strip() for c in df.columns]
df = df[df['Prop Firm'].notna() & (df['Prop Firm'].astype(str).str.strip() != '')]
df = df[df['Prop Firm'].astype(str).str.strip() != 'nan'].copy()

# European decimal: a number like "573,79" — comma followed by exactly 1-2 digits at end, no period
def is_european_decimal(s):
    s = str(s).strip()
    return bool(s and re.search(r'^-?\$?[\d.,]+,\d{2}$', s) and '.' not in s)

def parse_current(v):
    """Current parse_currency behavior"""
    try: return float(str(v).replace('$','').replace(',','').strip())
    except: return 0.0

def parse_fixed(v):
    """Fixed parse_currency behavior"""
    s = str(v).replace('$','').replace('€','').replace('£','').strip()
    if not s or s.lower() == 'nan': return 0.0
    # European decimal: comma before exactly 2 digits at end, no period
    if re.search(r',\d{2}$', s) and '.' not in s:
        last_comma = s.rfind(',')
        s = s[:last_comma].replace(',', '').replace('.', '') + '.' + s[last_comma+1:]
    else:
        s = s.replace(',', '')
    try: return float(s)
    except: return 0.0

hedge_cols = [
    'Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5',
    'Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
    'Hedge Result 5.1','Hedge Result 6','Hedge Result 7'
]

print("=== Malformatted values (European decimal notation) ===\n")
bad_rows = []
for col in hedge_cols:
    if col not in df.columns: continue
    for idx, val in df[col].items():
        if is_european_decimal(val):
            old = parse_current(val)
            new = parse_fixed(val)
            diff = new - old
            bad_rows.append({'col': col, 'idx': idx, 'val': val, 'old': old, 'new': new, 'diff': diff,
                            'firm': df.at[idx, 'Prop Firm'], 'status': df.at[idx, 'Status']})
            print(f"  Col={col:20s}  idx={idx:4d}  val={val!r:12s}  old={old:>12,.2f}  new={new:>10,.2f}  Δ={diff:>+12,.2f}"
                  f"  [{df.at[idx,'Prop Firm']}  {df.at[idx,'Status']}]")

if not bad_rows:
    print("  None found!")

total_correction = sum(r['diff'] for r in bad_rows)
print(f"\nTotal correction from fixing malformatted values: {total_correction:>+12,.2f}")
print(f"Expected correction needed: +57,125.04")
print(f"Remaining gap after fix: {total_correction - 57125.04:>+12,.2f}")

# Also show current vs fixed totals for key cols
print("\n=== Column sums: current vs fixed ===")
for col in ['Hedge Result 2.1','Hedge Result 3.1']:
    if col in df.columns:
        cur = df[col].apply(parse_current).sum()
        fix = df[col].apply(parse_fixed).sum()
        print(f"  {col}: current={cur:>12,.2f}  fixed={fix:>12,.2f}  Δ={fix-cur:>+12,.2f}")

# Full total
fd_cols = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
           'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
p1_cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']

total_fix = sum(df[c].apply(parse_fixed).sum() for c in fd_cols+p1_cols if c in df.columns)
total_cur = sum(df[c].apply(parse_current).sum() for c in fd_cols+p1_cols if c in df.columns)
print(f"\n  SUM(J:N)+SUM(U:AA)  current  = {total_cur:>12,.2f}")
print(f"  SUM(J:N)+SUM(U:AA)  fixed    = {total_fix:>12,.2f}")
print(f"  Sheet expects               = {-30959.91:>12,.2f}")
print(f"  Remaining diff after fix    = {total_fix - (-30959.91):>+12,.2f}")
