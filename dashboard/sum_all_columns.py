"""Sum ALL hedge-related columns to find the full picture"""
import pandas as pd
import requests
from io import StringIO
import math

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

def parse_val(val):
    """Parse currency/number value"""
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

# Filter to valid rows
df = df[df['Prop Firm'].notna()]
print(f"Valid rows: {len(df)}")

# Sum all fee columns
total_fee = df['Fee'].apply(parse_val).sum()
total_activation = df['Activation Fee'].apply(parse_val).sum() if 'Activation Fee' in df.columns else 0
print(f"\nFees:")
print(f"  Fee column: ${total_fee:,.2f}")
print(f"  Activation Fee: ${total_activation:,.2f}")
print(f"  TOTAL FEES: ${total_fee + total_activation:,.2f}")

# Sum hedge columns - Phase 1
p1_hedges = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
total_p1_hedge = sum(df[col].apply(parse_val).sum() for col in p1_hedges if col in df.columns)
hedge_net_p1 = df['Hedge Net'].apply(parse_val).sum() if 'Hedge Net' in df.columns else 0

print(f"\nPhase 1 Hedging:")
print(f"  Individual Results Sum: ${total_p1_hedge:,.2f}")
print(f"  Hedge Net column: ${hedge_net_p1:,.2f}")

# Sum hedge columns - Funded phase
funded_hedges = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
total_funded_hedge = sum(df[col].apply(parse_val).sum() for col in funded_hedges if col in df.columns)
hedge_net_funded = df['Hedge Net.1'].apply(parse_val).sum() if 'Hedge Net.1' in df.columns else 0

print(f"\nFunded Hedging:")
print(f"  Individual Results Sum: ${total_funded_hedge:,.2f}")
print(f"  Hedge Net.1 column: ${hedge_net_funded:,.2f}")

# Sum Hedge Day columns (1-34)
hedge_days_total = 0
for i in range(1, 35):
    col = f'Hedge Day {i}'
    if col in df.columns:
        hedge_days_total += df[col].apply(parse_val).sum()
print(f"\nHedge Days (1-34): ${hedge_days_total:,.2f}")

print(f"\nTOTAL ALL HEDGING: ${total_p1_hedge + total_funded_hedge + hedge_days_total:,.2f}")
print(f"Hedge Net columns only: ${hedge_net_p1 + hedge_net_funded:,.2f}")

# Sum payouts
payouts = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']
total_payouts = sum(df[col].apply(parse_val).sum() for col in payouts if col in df.columns)
print(f"\nTotal Payouts: ${total_payouts:,.2f}")

# Sum farming
total_farming = df['Farming Net'].apply(parse_val).sum() if 'Farming Net' in df.columns else 0
print(f"Total Farming: ${total_farming:,.2f}")

# Sheet expects (from screenshot):
# Completed + In Progress = Total
# Fees: 35528.18 + 38441.23 = 73,969.41
# Hedge: 10309.60 + (-33469.18) = -23,159.58
# Farm: 582.72 + 6604.17 = 7,186.89
# Payouts: 43023.63 + 69459.76 = 112,483.39

print("\n=== SHEET EXPECTED TOTALS ===")
print(f"Fees:    $73,969.41")
print(f"Hedge:   $-23,159.58")
print(f"Farm:    $7,186.89")
print(f"Payouts: $112,483.39")
