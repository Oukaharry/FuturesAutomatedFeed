"""Check if last few rows account for the $1.69 hedging and $0.42 payout differences.
Theory: the Stats formula has a specific row range that excludes recently added rows."""
import requests, io, sys
import pandas as pd
from decimal import Decimal, InvalidOperation

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"
sys.path.insert(0, '.')

csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
resp = requests.get(csv_url, timeout=30)
df = pd.read_csv(io.StringIO(resp.text), header=None)

# Find header
for i in range(5):
    if df.iloc[i].astype(str).str.contains('Prop Firm', case=False).any():
        header_idx = i
        break
df = pd.read_csv(io.StringIO(resp.text), header=header_idx)
df = df[df['Prop Firm'].notna() & (df['Prop Firm'].astype(str).str.strip() != '')]
print(f"Total valid rows: {len(df)}")

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
PAYOUT = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']

# Cumulative sums from the end
print("\n=== CUMULATIVE SUMS FROM THE END (last N rows) ===")
print(f"{'Rows excluded':>15s} {'Hedge partial':>15s} {'Cum Hedge':>12s} {'Payout partial':>15s} {'Cum Payout':>12s}")

cum_hedge = Decimal('0')
cum_payout = Decimal('0')
total_hedge = Decimal('-26646.11')
total_payout = Decimal('145295.62')
stats_hedge = Decimal('-26644.42')
stats_payout = Decimal('145295.20')

target_hedge_diff = stats_hedge - total_hedge  # 1.69
target_payout_diff = stats_payout - total_payout  # -0.42

print(f"\nTarget hedge diff (Stats - CSV): {target_hedge_diff}")
print(f"Target payout diff (Stats - CSV): {target_payout_diff}")
print()

for n in range(1, 20):
    row = df.iloc[-n]
    
    row_hedge = sum(parse_dec(row.get(c)) for c in P1_HEDGE + FUNDED_HEDGE)
    row_payout = sum(parse_dec(row.get(c)) for c in PAYOUT)
    
    cum_hedge += row_hedge
    cum_payout += row_payout
    
    # If excluding these rows, the remaining sum would be total - cum
    remaining_hedge = total_hedge - cum_hedge
    remaining_payout = total_payout - cum_payout
    
    hedge_match = "✓" if remaining_hedge == stats_hedge else ""
    payout_match = "✓" if remaining_payout == stats_payout else ""
    
    print(f"  Last {n:2d} row(s): hedge={row_hedge:>10}, cum={cum_hedge:>10}, remain={remaining_hedge:>12} {hedge_match} | payout={row_payout:>10}, cum={cum_payout:>10}, remain={remaining_payout:>12} {payout_match}")

# Also check from the beginning
print("\n=== CUMULATIVE SUMS FROM THE BEGINNING ===")
cum_hedge2 = Decimal('0')
cum_payout2 = Decimal('0')
for n in range(len(df)):
    row = df.iloc[n]
    row_hedge = sum(parse_dec(row.get(c)) for c in P1_HEDGE + FUNDED_HEDGE)
    row_payout = sum(parse_dec(row.get(c)) for c in PAYOUT)
    cum_hedge2 += row_hedge
    cum_payout2 += row_payout
    
    if cum_hedge2 == stats_hedge:
        print(f"  Hedge matches Stats at row {n} (first {n+1} rows)")
    if cum_payout2 == stats_payout:
        print(f"  Payout matches Stats at row {n} (first {n+1} rows)")

# If none match, try the theory: Stats formula has a specific range
# Check: what would each row need to contribute to explain the diffs
print(f"\n=== LAST 10 ROWS DETAIL ===")
for n in range(1, 11):
    idx = len(df) - n
    row = df.iloc[idx]
    prop = row.get('Prop Firm', '')
    date = row.get('Date Purchased', '')
    fee = parse_dec(row.get('Fee'))
    h_vals = [(c, parse_dec(row.get(c))) for c in P1_HEDGE + FUNDED_HEDGE]
    p_vals = [(c, parse_dec(row.get(c))) for c in PAYOUT]
    h_total = sum(v for _, v in h_vals)
    p_total = sum(v for _, v in p_vals)
    h_nonzero = [(c.replace('Hedge Result ','HR'), v) for c, v in h_vals if v != 0]
    p_nonzero = [(c, v) for c, v in p_vals if v != 0]
    print(f"  Row {idx}: {prop}, {date}, fee={fee}, hedge_total={h_total} {h_nonzero}, payout_total={p_total} {p_nonzero}")
