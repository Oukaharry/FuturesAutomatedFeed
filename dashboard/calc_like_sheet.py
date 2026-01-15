"""Calculate like the sheet: Completed vs In Progress"""
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

# Sheet's logic seems to be:
# "Completed" = Phase 1 Failed (Status P1 = Fail) + Funded Completed/Failed
# "In Progress" = Still active (Phase 1 Pass/ongoing + Funded Pass/ongoing)

# Let's try: Completed = P1 Fail OR Funded Fail OR Funded Completed
# In Progress = everything else

def is_completed(row):
    status_p1 = str(row['Status P1']).strip().lower()
    status = str(row['Status']).strip().lower()
    
    # Completed if:
    # - Status P1 is Fail (Phase 1 failed)
    # - OR Status is Fail/Completed (Funded phase ended)
    return status_p1 == 'fail' or status in ['fail', 'completed']

def calc_row_values(row):
    fee = parse_val(row.get('Fee', 0)) + parse_val(row.get('Activation Fee', 0))
    
    # Individual hedge results (NOT Hedge Net which is a calculated field)
    hedge_p1 = sum(parse_val(row.get(f'Hedge Result {i}', 0)) for i in range(1, 6))
    hedge_funded = sum(parse_val(row.get(col, 0)) for col in 
                       ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 
                        'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7'])
    hedge_days = sum(parse_val(row.get(f'Hedge Day {i}', 0)) for i in range(1, 35))
    
    total_hedge = hedge_p1 + hedge_funded + hedge_days
    
    payouts = sum(parse_val(row.get(f'Payout {i}', 0)) for i in range(1, 5))
    farm = parse_val(row.get('Farming Net', 0))
    
    return fee, total_hedge, payouts, farm

# Split data
completed_rows = df[df.apply(is_completed, axis=1)]
inprogress_rows = df[~df.apply(is_completed, axis=1)]

print(f"Completed rows: {len(completed_rows)}")
print(f"In Progress rows: {len(inprogress_rows)}")

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

print("\n=== OUR CALCULATION ===")
print("COMPLETED:")
print(f"  Fees:    -${completed_fees:,.2f}")
print(f"  Hedge:   ${completed_hedge:,.2f}")
print(f"  Farm:    ${completed_farm:,.2f}")
print(f"  Payouts: ${completed_payouts:,.2f}")
completed_net = -completed_fees + completed_hedge + completed_farm + completed_payouts
print(f"  Net:     ${completed_net:,.2f}")

print("\nIN PROGRESS:")
print(f"  Fees:    -${inprogress_fees:,.2f}")
print(f"  Hedge:   ${inprogress_hedge:,.2f}")
print(f"  Farm:    ${inprogress_farm:,.2f}")
print(f"  Payouts: ${inprogress_payouts:,.2f}")
inprogress_net = -inprogress_fees + inprogress_hedge + inprogress_farm + inprogress_payouts
print(f"  Net:     ${inprogress_net:,.2f}")

print("\n=== SHEET VALUES (from screenshot) ===")
print("COMPLETED:")
print(f"  Fees:    -$35,528.18")
print(f"  Hedge:   $10,309.60")
print(f"  Farm:    $582.72")
print(f"  Payouts: $43,023.63")
print(f"  Net:     $20,380.90")

print("\nIN PROGRESS:")
print(f"  Fees:    -$38,441.23")
print(f"  Hedge:   -$33,469.18")
print(f"  Farm:    $6,604.17")
print(f"  Payouts: $69,459.76")
print(f"  Net:     $6,146.65")
