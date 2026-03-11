"""Debug: Compare Chris DB hedging results vs what Google Sheet shows.
Finds which specific evaluations cause the ~$578 hedging difference."""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data
from utils.data_processor import calculate_statistics

def parse_currency(val):
    """Parse a currency string or number to float."""
    if val is None or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace('$', '').replace(',', '').replace(' ', '')
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0

client_id = 'Chris'
data = get_client_data(client_id)
evaluations = data.get('evaluations', [])
print(f"Total evaluations for {client_id}: {len(evaluations)}")

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

total_p1 = 0.0
total_funded = 0.0
total_hedge_days = 0.0
completed_hedging = 0.0
inprogress_hedging = 0.0

print("\n=== Per-Row Hedging Breakdown ===")
for i, ev in enumerate(evaluations):
    firm = ev.get('Prop Firm', '?')
    acc = ev.get('Account Number', '?')
    status_p1 = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '')).strip()
    
    p1_hedges = round(sum(parse_currency(ev.get(col)) for col in P1_HEDGE_COLS), 2)
    funded_hedges = round(sum(parse_currency(ev.get(col)) for col in FUNDED_HEDGE_COLS), 2)
    hedge_days = round(sum(parse_currency(ev.get(col)) for col in HEDGE_DAY_COLS), 2)
    
    total_p1 += p1_hedges
    total_funded += funded_hedges
    total_hedge_days += hedge_days
    
    row_total = p1_hedges + funded_hedges
    
    is_p1_fail = status_p1 == 'Fail'
    is_funded_fail = status_funded == 'Fail'
    is_funded_completed = status_funded == 'Completed'
    is_funded_ended = is_funded_fail or is_funded_completed
    
    # Completed hedging logic (same as calculate_statistics)
    row_completed = 0.0
    if is_p1_fail:
        row_completed += p1_hedges
    if is_funded_ended:
        row_completed += funded_hedges + p1_hedges
    
    if abs(row_total) > 0.01 or abs(hedge_days) > 0.01:
        print(f"  Row {i}: {firm} / {acc} | P1={status_p1} Fund={status_funded} | P1 Hedge={p1_hedges:.2f} Fund Hedge={funded_hedges:.2f} HedgeDays={hedge_days:.2f} | Completed contrib={row_completed:.2f}")
    
    completed_hedging += row_completed
    inprogress_hedging += row_total

# Also get Hedge Net columns for comparison
total_hedge_net = 0.0
total_hedge_net1 = 0.0
for ev in evaluations:
    hn = parse_currency(ev.get('Hedge Net'))
    hn1 = parse_currency(ev.get('Hedge Net.1'))
    total_hedge_net += hn
    total_hedge_net1 += hn1

print(f"\n=== TOTALS ===")
print(f"Sum of P1 Hedge Results (J-N): ${total_p1:.2f}")
print(f"Sum of Funded Hedge Results (U-AA): ${total_funded:.2f}")
print(f"Sum of Hedge Day cols: ${total_hedge_days:.2f}")
print(f"Total In-progress Hedging (P1+Funded, all rows): ${inprogress_hedging:.2f}")
print(f"Total Completed Hedging (SUMIF logic): ${completed_hedging:.2f}")
print(f"\nHedge Net column sum: ${total_hedge_net:.2f}")
print(f"Hedge Net.1 column sum: ${total_hedge_net1:.2f}")
print(f"Combined Hedge Net: ${total_hedge_net + total_hedge_net1:.2f}")

# Now run the actual calculate_statistics
stats = calculate_statistics(evaluations, None, None)
cf = stats['cashflow_inprogress']
pc = stats['profitability_completed']
print(f"\n=== calculate_statistics() results ===")
print(f"In-progress hedging: ${cf['hedging_results']:.2f}")
print(f"In-progress farming: ${cf['farming_results']:.2f}")
print(f"In-progress payouts: ${cf['payouts']:.2f}")
print(f"In-progress fees: ${cf['challenge_fees']:.2f}")
print(f"Completed hedging: ${pc['hedging_results']:.2f}")
print(f"Completed farming: ${pc['farming_results']:.2f}")
print(f"Completed payouts: ${pc['payouts']:.2f}")
print(f"Completed fees: ${pc['challenge_fees']:.2f}")

print(f"\n=== DIFFS FROM SHEET ===")
sheet_ip_hedging = -16555.37
sheet_cp_hedging = -1726.42
sheet_ip_farming = 9463.34
sheet_cp_farming = 6330.84
sheet_ip_payouts = 125768.58
sheet_cp_payouts = 115465.98
print(f"In-progress Hedging diff: ${cf['hedging_results'] - sheet_ip_hedging:.2f} (DB={cf['hedging_results']:.2f} Sheet={sheet_ip_hedging:.2f})")
print(f"Completed Hedging diff: ${pc['hedging_results'] - sheet_cp_hedging:.2f} (DB={pc['hedging_results']:.2f} Sheet={sheet_cp_hedging:.2f})")
print(f"In-progress Farming diff: ${cf['farming_results'] - sheet_ip_farming:.2f}")
print(f"Completed Farming diff: ${pc['farming_results'] - sheet_cp_farming:.2f}")
print(f"In-progress Payouts diff: ${cf['payouts'] - sheet_ip_payouts:.2f}")
print(f"Completed Payouts diff: ${pc['payouts'] - sheet_cp_payouts:.2f}")

# Check for any rows where Hedge Net column disagrees with sum of individual hedges
print(f"\n=== Hedge Net vs Sum-of-Parts Comparison ===")
for i, ev in enumerate(evaluations):
    p1_sum = round(sum(parse_currency(ev.get(col)) for col in P1_HEDGE_COLS), 2)
    funded_sum = round(sum(parse_currency(ev.get(col)) for col in FUNDED_HEDGE_COLS), 2)
    hedge_net = parse_currency(ev.get('Hedge Net'))
    hedge_net1 = parse_currency(ev.get('Hedge Net.1'))
    
    p1_diff = abs(p1_sum - hedge_net)
    fund_diff = abs(funded_sum - hedge_net1)
    
    if p1_diff > 0.01 or fund_diff > 0.01:
        firm = ev.get('Prop Firm', '?')
        acc = ev.get('Account Number', '?')
        print(f"  Row {i}: {firm}/{acc} | P1: sum={p1_sum:.2f} net_col={hedge_net:.2f} diff={p1_diff:.2f} | Fund: sum={funded_sum:.2f} net_col={hedge_net1:.2f} diff={fund_diff:.2f}")
