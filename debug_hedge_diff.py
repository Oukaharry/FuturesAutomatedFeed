"""Analyze activation fees and net profit components to reconcile with sheet."""
import json, sys
sys.path.insert(0, '.')
from dashboard.database import get_connection
from utils.data_processor import parse_currency

with get_connection() as conn:
    row = conn.execute('SELECT evaluations, statistics FROM clients_data WHERE client_id=?', ('Joe',)).fetchone()

evals = json.loads(row[0])
stats = json.loads(row[1])

print('Stored profitability_completed:')
pc = stats['profitability_completed']
for k, v in pc.items():
    print(f'  {k}: ${v:,.2f}')

net_with_act = pc['payouts'] + pc['hedging_results'] + pc['farming_results'] - pc['challenge_fees'] - pc.get('activation_fee', 0)
net_without_act = pc['payouts'] + pc['hedging_results'] + pc['farming_results'] - pc['challenge_fees']
print(f'\nNet profit WITHOUT activation fee: ${net_without_act:,.2f}')
print(f'Net profit WITH    activation fee: ${net_with_act:,.2f}')
print(f'Sheet net profit:                  $27,057.53')
print(f'Stored net_profit:                 ${pc["net_profit"]:,.2f}')

# Break down by status group for hedging
print('\n=== Hedging breakdown by status group ===')
h_groups = {}
for ev in evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    from utils.data_processor import parse_currency as pc2
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                         'Hedge Result 5.1', 'Hedge Result 6.1', 'Hedge Result 7.1']
    p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    fh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
    key = (sp1, sf)
    if key not in h_groups:
        h_groups[key] = {'p1h': 0.0, 'fh': 0.0, 'count': 0}
    h_groups[key]['p1h'] += p1h
    h_groups[key]['fh'] += fh
    h_groups[key]['count'] += 1

print(f"{'P1':<20} {'Funded':<15} {'P1 Hedge':>12} {'Funded Hedge':>14} {'Total':>12}  N")
print('-' * 80)
for (sp1, sf), d in sorted(h_groups.items(), key=lambda x: -(abs(x[1]['p1h']) + abs(x[1]['fh']))):
    tot = d['p1h'] + d['fh']
    print(f"{sp1:<20} {sf:<15} ${d['p1h']:>10,.2f} ${d['fh']:>12,.2f} ${tot:>10,.2f}  {d['count']}")

# Code logic: P1=Fail -> add p1h; Status=Fail/Completed -> add fh+p1h
code_total = 0.0
for (sp1, sf), d in h_groups.items():
    is_p1_fail = sp1 == 'Fail'
    is_funded_ended = sf in ('Fail', 'Completed')
    if is_p1_fail:
        code_total += d['p1h']
    if is_funded_ended:
        code_total += d['fh'] + d['p1h']

print(f'\nCode-computed hedging (current logic): ${code_total:,.2f}')

# Sheet logic: P1=Fail -> add p1h; Status=Fail -> add fh+p1h; Status=Completed -> add fh+p1h
# What if sheet only adds funded_hedge for funded ended, not p1h again?
alt1 = 0.0
for (sp1, sf), d in h_groups.items():
    is_p1_fail = sp1 == 'Fail'
    is_funded_ended = sf in ('Fail', 'Completed')
    if is_p1_fail:
        alt1 += d['p1h']
    if is_funded_ended:
        alt1 += d['fh']   # only funded hedge, not p1h again

print(f'Alt1 hedging (fh only for funded ended):    ${alt1:,.2f}')
print(f'Sheet hedging (expected):                   $-42,160.47')

# Alt2: include p1h only for funded_fail not funded_completed
alt2 = 0.0
for (sp1, sf), d in h_groups.items():
    sp1_ = (sp1 == 'Fail')
    is_funded_fail = sf == 'Fail'
    is_funded_completed = sf == 'Completed'
    if sp1_:
        alt2 += d['p1h']
    if is_funded_fail:
        alt2 += d['fh'] + d['p1h']
    if is_funded_completed:
        alt2 += d['fh']

print(f'Alt2 (fh+p1h for fail, fh only for completed): ${alt2:,.2f}')
