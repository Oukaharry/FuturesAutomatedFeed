"""
Debug script: compare local DB profitability_completed vs expected sheet values.
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

from dashboard.database import get_all_clients
from utils.data_processor import calculate_statistics, parse_currency

print("Fetching all clients from DB...")
all_clients = get_all_clients()
print(f"Total clients: {len(all_clients)}")

# Collect ALL evaluations across all clients
evaluations = []
for client_id, data in all_clients.items():
    if data and data.get('evaluations'):
        for ev in data['evaluations']:
            if isinstance(ev, dict):
                ev['_client_id'] = client_id
                evaluations.append(ev)

print(f"Total evaluations: {len(evaluations)}")

stats = calculate_statistics(evaluations, None, None)
prof = stats['profitability_completed']

print()
print("=== PROFITABILITY - COMPLETED (LOCAL DB) ===")
print(f"  Challenge Fees:   ${prof['challenge_fees']:,.2f}")
print(f"  Hedging Results:  ${prof['hedging_results']:,.2f}")
print(f"  Farming Results:  ${prof['farming_results']:,.2f}")
print(f"  Payouts:          ${prof['payouts']:,.2f}")
print(f"  Activation Fee:   ${prof['activation_fee']:,.2f}")
print(f"  Net Profit:       ${prof['net_profit']:,.2f}")

print()
print("=== STATUS BREAKDOWN ===")
statuses = {}
for ev in evaluations:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    key = f"P1={sp1}, Status={sf}"
    statuses[key] = statuses.get(key, 0) + 1
for k, v in sorted(statuses.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

print()
print("=== PER-EVALUATION DEBUG (Completed rows only) ===")
print(f"{'Client':<20} {'P1':<10} {'Status':<12} {'Fee':>10} {'P1Hedge':>10} {'FdHedge':>10} {'HedgeDays':>10} {'Payouts':>10}")
print("-" * 100)

for ev in evaluations:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    is_p1_fail = sp1 == 'Fail'
    is_funded_completed = sf == 'Completed'
    is_funded_fail = sf == 'Fail'
    is_funded_ended = is_funded_completed or is_funded_fail

    if not (is_p1_fail or is_funded_ended):
        continue

    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    fee = parse_currency(ev.get('Fee'))
    p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
    hdays = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
    payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))

    client = str(ev.get('Client ID', ev.get('Account', 'Unknown')))[:19]
    print(f"  {client:<19} {sp1:<10} {sf:<12} {fee:>10.2f} {p1h:>10.2f} {fdh:>10.2f} {hdays:>10.2f} {payouts:>10.2f}")

print()
print("=== DOUBLE-COUNT CHECK ===")
print("Note: In data_processor.py, when is_funded_ended, BOTH p1_hedges AND funded_hedges are added.")
print("      When ALSO is_p1_fail, p1_hedges gets added AGAIN (double-counted).")
double_count_cases = 0
double_count_amount = 0.0
for ev in evaluations:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    is_p1_fail = sp1 == 'Fail'
    is_funded_ended = sf in ('Fail', 'Completed')

    if is_p1_fail and is_funded_ended:
        P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        double_count_cases += 1
        double_count_amount += p1h
        client = str(ev.get('Client ID', ev.get('Account', 'Unknown')))[:30]
        print(f"  DOUBLE-COUNT: {client}, P1={sp1}, Status={sf}, P1Hedge={p1h:.2f}")

if double_count_cases == 0:
    print("  No double-count cases found.")
else:
    print(f"\n  TOTAL double-counted P1 hedge: ${double_count_amount:,.2f} across {double_count_cases} rows")
