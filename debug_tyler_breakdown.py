"""Debug: Detailed breakdown of Tyler's cashflow differences."""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

TYLER_SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"
sheet_url = f"https://docs.google.com/spreadsheets/d/{TYLER_SHEET_ID}/edit?gid=0#gid=0"

# Fetch fresh data
result = fetch_evaluations(sheet_url)
if isinstance(result, tuple):
    evals, notes = result
else:
    evals = result

print(f"Total evaluations: {len(evals)}")

# Check what the Sheet formulas SHOULD produce:
# Challenge Fees = -SUM(Fee column only, NOT activation fee)
# vs Python code which does fee + activation_fee

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

total_fee_only = 0.0
total_activation_fee = 0.0
total_fee_plus_activation = 0.0
total_p1_hedges = 0.0
total_funded_hedges = 0.0
total_farming = 0.0
total_payouts = 0.0

for ev in evals:
    fee = parse_currency(ev.get('Fee'))
    act_fee = parse_currency(ev.get('Activation Fee'))
    total_fee_only += fee
    total_activation_fee += act_fee
    total_fee_plus_activation += fee + act_fee
    
    p1_h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    funded_h = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
    total_p1_hedges += p1_h
    total_funded_hedges += funded_h
    
    total_farming += sum(parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS)
    total_payouts += sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))

print(f"\n=== CHALLENGE FEES BREAKDOWN ===")
print(f"SUM(Fee only):                 ${total_fee_only:,.2f}")
print(f"SUM(Activation Fee only):      ${total_activation_fee:,.2f}")
print(f"SUM(Fee + Activation Fee):     ${total_fee_plus_activation:,.2f}")
print(f"-SUM(Fee only) [Sheet formula]: ${-total_fee_only:,.2f}")
print(f"")
print(f"Dashboard shows:   $60,731.37  (stored as positive)")
print(f"Sheet Stats shows: -$61,234.37")
print(f"Difference:        ${60731.37 - 61234.37:,.2f}")

print(f"\n=== HEDGING RESULTS BREAKDOWN ===")
print(f"SUM(P1 Hedges J:N):            ${total_p1_hedges:,.2f}")
print(f"SUM(Funded Hedges U:AA):       ${total_funded_hedges:,.2f}")
print(f"SUM(P1 + Funded):              ${total_p1_hedges + total_funded_hedges:,.2f}")
print(f"")
print(f"Dashboard shows:   -$26,236.11")
print(f"Sheet Stats shows: -$26,644.42")
print(f"Difference:        ${-26236.11 - (-26644.42):,.2f}")

print(f"\n=== FARMING RESULTS ===")
print(f"SUM(Hedge Days):               ${total_farming:,.2f}")
print(f"Dashboard shows:   $10,794.66")
print(f"Sheet Stats shows: $10,794.66")

print(f"\n=== PAYOUTS ===")
print(f"SUM(Payouts 1-4):              ${total_payouts:,.2f}")
print(f"Dashboard shows:   $145,295.62")
print(f"Sheet Stats shows: $145,295.20")
print(f"Difference:        ${145295.62 - 145295.20:,.2f}")

# Check if any columns have data the Python code might be parsing differently
print(f"\n=== SAMPLE ROW ANALYSIS (first 5 rows) ===")
for i, ev in enumerate(evals[:5]):
    fee = ev.get('Fee', '')
    act = ev.get('Activation Fee', '')
    print(f"Row {i}: Fee='{fee}' -> {parse_currency(fee):.2f}, ActFee='{act}' -> {parse_currency(act):.2f}, Firm='{ev.get('Prop Firm','')}'")

# Check for any rows where parsed values might differ
print(f"\n=== ROWS WITH NON-ZERO ACTIVATION FEE ===")
count = 0
for i, ev in enumerate(evals):
    act = parse_currency(ev.get('Activation Fee'))
    if abs(act) > 0.01:
        fee = parse_currency(ev.get('Fee'))
        print(f"Row {i}: Fee=${fee:.2f}, ActFee=${act:.2f}, Firm='{ev.get('Prop Firm','')}'")
        count += 1
print(f"Total rows with activation fee: {count}")

# Check for potential parsing issues with hedges
print(f"\n=== ROWS WITH HEDGE VALUES THAT MIGHT PARSE DIFFERENTLY ===")
for i, ev in enumerate(evals):
    for col in FUNDED_HEDGE_COLS:
        raw = ev.get(col, '')
        parsed = parse_currency(raw)
        if raw and str(raw).strip() not in ['', 'nan', '-', '0', '0.0', '$0.00'] and abs(parsed) < 0.01:
            print(f"Row {i}, {col}: raw='{raw}' -> parsed={parsed} (POTENTIAL ISSUE)")
