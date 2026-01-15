"""Debug Tsubasa sheet to understand categorization"""
import sys
sys.path.insert(0, '..')
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/edit?usp=sharing'

evals = fetch_evaluations(SHEET_URL)
print(f"Total records: {len(evals)}")

# Let's manually calculate what the sheet shows
# Screenshot shows:
# Profitability - Completed: Fees=-$35,528.18, Hedge=$10,309.60, Farm=$582.72, Payout=$43,023.63, Net=$20,380.90
# Profitability - In Progress: Fees=-$38,441.23, Hedge=-$33,469.18, Farm=$6,604.17, Payout=$69,459.76, Net=$6,146.65

# Let's categorize and see what we get
completed_fees = 0
completed_hedge = 0
completed_farm = 0
completed_payouts = 0

inprogress_fees = 0
inprogress_hedge = 0
inprogress_farm = 0
inprogress_payouts = 0

# Track statuses
status_counts = {}

for ev in evals:
    status_p1 = str(ev.get('Status P1', '')).strip()
    status = str(ev.get('Status', '')).strip()
    
    # Track all status combinations
    key = f"P1:{status_p1}|Funded:{status}"
    status_counts[key] = status_counts.get(key, 0) + 1
    
    fee = parse_currency(ev.get('Fee')) + parse_currency(ev.get('Activation Fee'))
    hedge = parse_currency(ev.get('Hedge Net')) + parse_currency(ev.get('Hedge Net.1'))
    farm = parse_currency(ev.get('Farming Net'))
    payouts = sum([parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5)])
    
    # The sheet's logic might be:
    # "Completed" = accounts where funded Status is Completed/Breached/Failed/Closed
    # "In Progress" = accounts still active (Status is empty or ongoing)
    
    is_funded_done = status.lower() in ['completed', 'breached', 'fail', 'failed', 'closed', 'payout']
    is_eval_failed = status_p1.lower() in ['fail', 'failed']
    
    # Try: Completed = (Funded finished) OR (Eval failed without getting funded)
    is_completed = is_funded_done or (is_eval_failed and not status)
    
    if is_completed:
        completed_fees += fee
        completed_hedge += hedge
        completed_farm += farm
        completed_payouts += payouts
    else:
        inprogress_fees += fee
        inprogress_hedge += hedge
        inprogress_farm += farm
        inprogress_payouts += payouts

print("\n=== STATUS COMBINATIONS ===")
for k, v in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

print("\n=== OUR CALCULATION (Fees as positive) ===")
print("COMPLETED:")
print(f"  Fees:    ${completed_fees:,.2f}")
print(f"  Hedge:   ${completed_hedge:,.2f}")
print(f"  Farm:    ${completed_farm:,.2f}")
print(f"  Payouts: ${completed_payouts:,.2f}")
print(f"  Net:     ${completed_payouts + completed_hedge + completed_farm - completed_fees:,.2f}")

print("\nIN PROGRESS:")
print(f"  Fees:    ${inprogress_fees:,.2f}")
print(f"  Hedge:   ${inprogress_hedge:,.2f}")
print(f"  Farm:    ${inprogress_farm:,.2f}")
print(f"  Payouts: ${inprogress_payouts:,.2f}")
print(f"  Net:     ${inprogress_payouts + inprogress_hedge + inprogress_farm - inprogress_fees:,.2f}")

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

# Calculate total to check if raw numbers match
total_fees = completed_fees + inprogress_fees
total_hedge = completed_hedge + inprogress_hedge
total_farm = completed_farm + inprogress_farm
total_payouts = completed_payouts + inprogress_payouts

sheet_total_fees = 35528.18 + 38441.23
sheet_total_hedge = 10309.60 + (-33469.18)
sheet_total_farm = 582.72 + 6604.17
sheet_total_payouts = 43023.63 + 69459.76

print("\n=== TOTALS COMPARISON ===")
print(f"Our Fees:    ${total_fees:,.2f} vs Sheet: ${sheet_total_fees:,.2f}")
print(f"Our Hedge:   ${total_hedge:,.2f} vs Sheet: ${sheet_total_hedge:,.2f}")
print(f"Our Farm:    ${total_farm:,.2f} vs Sheet: ${sheet_total_farm:,.2f}")
print(f"Our Payouts: ${total_payouts:,.2f} vs Sheet: ${sheet_total_payouts:,.2f}")
