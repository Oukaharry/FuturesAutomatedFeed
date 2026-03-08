"""Parse raw CSV hedge/payout columns with full precision, no rounding, and compare.
Also check for text values that SUM might treat differently."""
import requests, io, sys
import pandas as pd
from decimal import Decimal, InvalidOperation
import re

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

# Fetch raw CSV
csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
resp = requests.get(csv_url, timeout=30)
df = pd.read_csv(io.StringIO(resp.text), header=None)

# Find header row
header_idx = None
for i in range(5):
    row = df.iloc[i].astype(str)
    if row.str.contains('Prop Firm', case=False).any():
        header_idx = i
        break

df = pd.read_csv(io.StringIO(resp.text), header=header_idx)
cols = list(df.columns)
print(f"Data rows: {len(df)}, Header at: {header_idx}")

# Filter to valid rows (Prop Firm non-empty)
if 'Prop Firm' in cols:
    df = df[df['Prop Firm'].notna() & (df['Prop Firm'].astype(str).str.strip() != '')]
print(f"Valid data rows: {len(df)}")

# Sum hedge columns using FULL Decimal precision (no rounding)
def parse_decimal(val):
    """Parse currency to Decimal, preserving full precision. Returns None for text."""
    if pd.isna(val):
        return Decimal('0')
    s = str(val).strip()
    if not s or s == 'nan' or s == '-':
        return Decimal('0')
    # Remove $, commas
    s = s.replace('$', '').replace(',', '').strip()
    if not s or s == '-':
        return Decimal('0')
    # Handle parentheses for negative
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return Decimal(s)
    except InvalidOperation:
        return None  # True text - SUM ignores this

# Hedge columns (using actual column names from the header)
P1_HEDGE = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
PAYOUT = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']

# Pandas may have renamed duplicate columns with .1 suffix
# Let's check actual column names
duplicate_fix = {}
for c in df.columns:
    if c not in duplicate_fix:
        duplicate_fix[c] = c

# Compute sums with FULL precision and NO rounding
print(f"\n=== HEDGE SUMS (FULL DECIMAL PRECISION, NO ROUNDING) ===")
hedge_total_unrounded = Decimal('0')
hedge_total_rounded = Decimal('0')

for col_name in P1_HEDGE + FUNDED_HEDGE:
    if col_name not in df.columns:
        print(f"  WARNING: Column '{col_name}' not found!")
        continue
    
    col_sum_unrounded = Decimal('0')
    col_sum_rounded = Decimal('0')
    text_vals = []
    precision_vals = []
    
    for idx, raw in df[col_name].items():
        d = parse_decimal(raw)
        if d is None:
            text_vals.append((idx, raw))
            continue
        col_sum_unrounded += d
        col_sum_rounded += d.quantize(Decimal('0.01'))
        
        # Check precision
        if d != d.quantize(Decimal('0.01')):
            precision_vals.append((idx, raw, d))
    
    diff = col_sum_unrounded - col_sum_rounded
    mark = " ***" if diff != 0 else ""
    print(f"  {col_name:25s}: unrounded={col_sum_unrounded:>12}, rounded={col_sum_rounded:>12}, diff={diff}{mark}")
    if text_vals:
        print(f"    Text values ({len(text_vals)}): {text_vals[:3]}")
    if precision_vals:
        for idx, raw, d in precision_vals:
            print(f"    >2dp: row {idx}, raw='{raw}', decimal={d}")
    
    hedge_total_unrounded += col_sum_unrounded
    hedge_total_rounded += col_sum_rounded

print(f"\n  TOTAL unrounded: {hedge_total_unrounded}")
print(f"  TOTAL rounded:   {hedge_total_rounded}")
print(f"  Difference:      {hedge_total_unrounded - hedge_total_rounded}")
print(f"  Stats tab:       -26644.42")

print(f"\n=== PAYOUT SUMS (FULL DECIMAL PRECISION, NO ROUNDING) ===")
payout_total_unrounded = Decimal('0')
payout_total_rounded = Decimal('0')

for col_name in PAYOUT:
    if col_name not in df.columns:
        print(f"  WARNING: Column '{col_name}' not found!")
        continue
    
    col_sum_unrounded = Decimal('0')
    col_sum_rounded = Decimal('0')
    text_vals = []
    precision_vals = []
    
    for idx, raw in df[col_name].items():
        d = parse_decimal(raw)
        if d is None:
            text_vals.append((idx, raw))
            continue
        col_sum_unrounded += d
        col_sum_rounded += d.quantize(Decimal('0.01'))
        
        if d != d.quantize(Decimal('0.01')):
            precision_vals.append((idx, raw, d))
    
    diff = col_sum_unrounded - col_sum_rounded
    mark = " ***" if diff != 0 else ""
    print(f"  {col_name:15s}: unrounded={col_sum_unrounded:>12}, rounded={col_sum_rounded:>12}, diff={diff}{mark}")
    if text_vals:
        print(f"    Text values ({len(text_vals)}): {text_vals[:3]}")
    if precision_vals:
        for idx, raw, d in precision_vals:
            print(f"    >2dp: row {idx}, raw='{raw}', decimal={d}")
    
    payout_total_unrounded += col_sum_unrounded
    payout_total_rounded += col_sum_rounded

print(f"\n  TOTAL unrounded: {payout_total_unrounded}")
print(f"  TOTAL rounded:   {payout_total_rounded}")
print(f"  Difference:      {payout_total_unrounded - payout_total_rounded}")
print(f"  Stats tab:       145295.20")

# Compute fees too
print(f"\n=== FEE SUM ===")
fee_total = Decimal('0')
activation_total = Decimal('0')
for idx, raw in df['Fee'].items():
    d = parse_decimal(raw)
    if d is not None:
        fee_total += d
if 'Activation Fee' in df.columns:
    for idx, raw in df['Activation Fee'].items():
        d = parse_decimal(raw)
        if d is not None:
            activation_total += d
print(f"  Fee sum: {fee_total}")
print(f"  Activation sum: {activation_total}")
print(f"  Challenge fees (fee + activation): {fee_total + activation_total}")
print(f"  Stats tab: 61234.37")
