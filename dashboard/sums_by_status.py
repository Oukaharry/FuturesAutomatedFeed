"""Calculate stats by status to match sheet"""
import pandas as pd
import requests
from io import StringIO

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

def parse_val(val):
    if pd.isna(val) or val == '' or val == '-':
        return 0.0
    try:
        clean = str(val).replace('$', '').replace(',', '').replace(' ', '')
        if clean == '' or clean == '-':
            return 0.0
        return float(clean)
    except:
        return 0.0

response = requests.get(SHEET_URL)
df = pd.read_csv(StringIO(response.text), header=1)
df = df[df['Prop Firm'].notna()]

# The Stats sheet likely uses SUMIF on Status column
# Let's group by funded Status and sum values

# First, let's see what Status values we have
print("=== FUNDED STATUS VALUES ===")
print(df['Status'].value_counts())

print("\n=== STATUS P1 VALUES ===")
print(df['Status P1'].value_counts())

# Now calculate sums by Status
print("\n=== SUMS BY FUNDED STATUS ===")
for status in df['Status'].unique():
    subset = df[df['Status'] == status]
    fees = subset['Fee'].apply(parse_val).sum()
    hedge_p1 = sum(subset[col].apply(parse_val).sum() for col in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5'] if col in subset.columns)
    hedge_funded = sum(subset[col].apply(parse_val).sum() for col in ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7'] if col in subset.columns)
    
    # Hedge Days
    hedge_days = sum(subset[f'Hedge Day {i}'].apply(parse_val).sum() for i in range(1, 35) if f'Hedge Day {i}' in subset.columns)
    
    payouts = sum(subset[col].apply(parse_val).sum() for col in ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4'] if col in subset.columns)
    farm = subset['Farming Net'].apply(parse_val).sum() if 'Farming Net' in subset.columns else 0
    
    total_hedge = hedge_p1 + hedge_funded + hedge_days
    
    print(f"\nStatus: '{status}' ({len(subset)} rows)")
    print(f"  Fees:    ${fees:,.2f}")
    print(f"  Hedge:   ${total_hedge:,.2f} (P1: {hedge_p1:,.2f}, Funded: {hedge_funded:,.2f}, Days: {hedge_days:,.2f})")
    print(f"  Payouts: ${payouts:,.2f}")
    print(f"  Farm:    ${farm:,.2f}")

# Let's also check the individual hedge result columns
print("\n\n=== INDIVIDUAL HEDGE COLUMNS (All rows) ===")
hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1',
              'Hedge Result 6', 'Hedge Result 7']
for col in hedge_cols:
    if col in df.columns:
        total = df[col].apply(parse_val).sum()
        print(f"  {col}: ${total:,.2f}")
