"""Check for rows WITHOUT Prop Firm but WITH hedge or payout values.
These would be included in Stats SUM but excluded from Python calculation."""
import requests, io, sys
import pandas as pd
from decimal import Decimal, InvalidOperation

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
resp = requests.get(csv_url, timeout=30)

# Read with header detection
df_raw = pd.read_csv(io.StringIO(resp.text), header=None)
for i in range(5):
    if df_raw.iloc[i].astype(str).str.contains('Prop Firm', case=False).any():
        header_idx = i
        break

df = pd.read_csv(io.StringIO(resp.text), header=header_idx)
print(f"Total rows (all): {len(df)}")

# Identify rows WITHOUT Prop Firm
no_pf = df[df['Prop Firm'].isna() | (df['Prop Firm'].astype(str).str.strip() == '')]
print(f"Rows without Prop Firm: {len(no_pf)}")

def parse_dec(val):
    if pd.isna(val): return Decimal('0')
    s = str(val).strip().replace('$','').replace(',','')
    if not s or s == '-' or s == 'nan': return Decimal('0')
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    try: return Decimal(s)
    except: return Decimal('0')

P1_HEDGE = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
ALL_HEDGE = P1_HEDGE + FUNDED_HEDGE
PAYOUT = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']

# Check each no-Prop-Firm row for hedge/payout values
print(f"\n=== ROWS WITHOUT PROP FIRM WITH HEDGE OR PAYOUT VALUES ===")
ghost_hedge_total = Decimal('0')
ghost_payout_total = Decimal('0')
ghost_fee_total = Decimal('0')

for idx, row in no_pf.iterrows():
    h_total = sum(parse_dec(row.get(c)) for c in ALL_HEDGE)
    p_total = sum(parse_dec(row.get(c)) for c in PAYOUT)
    f_total = parse_dec(row.get('Fee'))
    a_total = parse_dec(row.get('Activation Fee')) if 'Activation Fee' in row.index else Decimal('0')
    
    if h_total != 0 or p_total != 0 or f_total != 0:
        ghost_hedge_total += h_total
        ghost_payout_total += p_total
        ghost_fee_total += f_total + a_total
        
        # Show some context
        nearby_vals = {}
        for c in ['Prop Firm', 'Account Size', 'Fee', 'Status P1', 'Status'] + ALL_HEDGE + PAYOUT:
            v = row.get(c)
            if pd.notna(v) and str(v).strip() and str(v).strip() != 'nan':
                nearby_vals[c] = v
        print(f"  Row {idx}: {nearby_vals}")

print(f"\n=== GHOST ROW TOTALS ===")
print(f"  Ghost hedge total:  {ghost_hedge_total}")
print(f"  Ghost payout total: {ghost_payout_total}")
print(f"  Ghost fee total:    {ghost_fee_total}")

print(f"\n=== EXPECTED VS ACTUAL ===")
print(f"  Hedge diff needed: +1.69 (Stats is less negative)")
print(f"  Ghost hedge:       {ghost_hedge_total}")
print(f"  Payout diff needed: -0.42 (Stats is smaller)")
print(f"  Ghost payout:      {ghost_payout_total}")

if ghost_hedge_total != 0 or ghost_payout_total != 0:
    # Our total + ghost should equal Stats
    our_hedge = Decimal('-26646.11')
    our_payout = Decimal('145295.62')
    adjusted_hedge = our_hedge + ghost_hedge_total
    adjusted_payout = our_payout + ghost_payout_total
    print(f"\n  Adjusted hedge:  {adjusted_hedge} (Stats: -26644.42)")
    print(f"  Adjusted payout: {adjusted_payout} (Stats: 145295.20)")

# Also check: are there rows with Prop Firm that DON'T look like normal data rows?
# (e.g., summary rows, separator rows)
print(f"\n=== CHECKING FOR UNUSUAL PROP FIRM VALUES ===")
pf_vals = df['Prop Firm'].dropna().astype(str).str.strip()
unique_pf = pf_vals.value_counts()
print(f"Unique Prop Firm values: {len(unique_pf)}")
for pf, count in unique_pf.items():
    if count <= 2 or len(pf) < 3:
        print(f"  '{pf}': {count} rows")
