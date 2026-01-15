"""Try inverted logic - maybe sheet does it opposite"""
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

# Maybe the sheet uses:
# "Completed" = Only Funded Completed (Status = 'Completed')  
# "In Progress" = Everything else

def is_only_completed(row):
    status = str(row['Status']).strip().lower()
    return status == 'completed'

def calc_row_values(row):
    fee = parse_val(row.get('Fee', 0)) + parse_val(row.get('Activation Fee', 0))
    
    hedge_p1 = sum(parse_val(row.get(f'Hedge Result {i}', 0)) for i in range(1, 6))
    hedge_funded = sum(parse_val(row.get(col, 0)) for col in 
                       ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 
                        'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7'])
    hedge_days = sum(parse_val(row.get(f'Hedge Day {i}', 0)) for i in range(1, 35))
    
    total_hedge = hedge_p1 + hedge_funded + hedge_days
    
    payouts = sum(parse_val(row.get(f'Payout {i}', 0)) for i in range(1, 5))
    farm = parse_val(row.get('Farming Net', 0))
    
    return fee, total_hedge, payouts, farm

# Split data - ONLY Status='Completed' vs everything else
completed_rows = df[df.apply(is_only_completed, axis=1)]
inprogress_rows = df[~df.apply(is_only_completed, axis=1)]

print(f"Completed rows (Status='Completed' only): {len(completed_rows)}")
print(f"In Progress rows (everything else): {len(inprogress_rows)}")

# Calculate sums
completed_fees = completed_hedge = completed_payouts = completed_farm = 0
for _, row in completed_rows.iterrows():
    f, h, p, farm = calc_row_values(row)
    completed_fees += f
    completed_hedge += h
    completed_payouts += p
    completed_farm += farm

inprogress_fees = inprogress_hedge = inprogress_payouts = inprogress_farm = 0
for _, row in inprogress_rows.iterrows():
    f, h, p, farm = calc_row_values(row)
    inprogress_fees += f
    inprogress_hedge += h
    inprogress_payouts += p
    inprogress_farm += farm

print("\n=== COMPLETED (Status='Completed' only) ===")
print(f"  Fees:    -${completed_fees:,.2f}")
print(f"  Hedge:   ${completed_hedge:,.2f}")
print(f"  Farm:    ${completed_farm:,.2f}")
print(f"  Payouts: ${completed_payouts:,.2f}")
completed_net = -completed_fees + completed_hedge + completed_farm + completed_payouts
print(f"  Net:     ${completed_net:,.2f}")

print("\n=== IN PROGRESS (Everything else) ===")
print(f"  Fees:    -${inprogress_fees:,.2f}")
print(f"  Hedge:   ${inprogress_hedge:,.2f}")
print(f"  Farm:    ${inprogress_farm:,.2f}")
print(f"  Payouts: ${inprogress_payouts:,.2f}")
inprogress_net = -inprogress_fees + inprogress_hedge + inprogress_farm + inprogress_payouts
print(f"  Net:     ${inprogress_net:,.2f}")

print("\n=== SHEET VALUES (from screenshot) ===")
print("COMPLETED: Fees=-$35,528.18, Hedge=$10,309.60, Farm=$582.72, Payouts=$43,023.63, Net=$20,380.90")
print("IN PROGRESS: Fees=-$38,441.23, Hedge=-$33,469.18, Farm=$6,604.17, Payouts=$69,459.76, Net=$6,146.65")

# Let's also try summing Hedge Days column which could be the Farming
print("\n\n=== CHECKING HEDGE DAYS AS POTENTIAL FARMING ===")
for i in range(1, 35):
    col = f'Hedge Day {i}'
    if col in df.columns:
        total = df[col].apply(parse_val).sum()
        if abs(total) > 1:
            print(f"  {col}: ${total:,.2f}")
