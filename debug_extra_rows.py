"""
Check if the 'U483' label in row 0 means only 483 valid data rows.
Look at rows 484+ to see if they have hedge data contributing to the -$319.83 gap.
"""
import sys, requests, io
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

def pc(v):
    """Fixed parse_currency"""
    import re
    if v is None: return 0.0
    try:
        s = str(v).replace('$','').replace('€','').replace('£','').strip()
        if not s or s.lower() == 'nan': return 0.0
        if re.search(r',\d{2}$', s):
            last = s.rfind(',')
            s = s[:last].replace(',','').replace('.','') + '.' + s[last+1:]
        else:
            s = s.replace(',','')
        return float(s)
    except: return 0.0

url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
df = pd.read_csv(io.StringIO(r.text), header=1, dtype=str)
df.columns = [str(c).strip() for c in df.columns]
df_all = df[df['Prop Firm'].notna() & ~df['Prop Firm'].astype(str).str.strip().isin(['', 'nan'])].copy()

print(f"Total data rows after filter: {len(df_all)}")
print(f"'U483' suggests 483 rows — we have {len(df_all)}")
print(f"Extra rows: {len(df_all) - 483}")

p1cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
fdcols = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
          'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']

# Rows from index 482 onwards (0-indexed, so row 483+ = indices 482+)
tail = df_all.iloc[483:]
print(f"\nRows 484+ hedge sums (potential 'phantom' rows):")
t_p1 = sum(tail[c].apply(pc).sum() for c in p1cols if c in tail.columns)
t_fd = sum(tail[c].apply(pc).sum() for c in fdcols if c in tail.columns)
print(f"  SUM(J:N)  rows 484+ = {t_p1:>10,.2f}")
print(f"  SUM(U:AA) rows 484+ = {t_fd:>10,.2f}")
print(f"  TOTAL             = {t_p1+t_fd:>10,.2f}")
print(f"  Remaining gap was = -319.83")

# Show what those extra rows look like
print(f"\nRows 484-510 overview:")
extra = df_all.iloc[483:]
print(extra[['Prop Firm','Account Size','Status P1','Status']].to_string())
