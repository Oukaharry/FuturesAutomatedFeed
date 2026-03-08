"""
Compare: sum of individual hedge result columns vs Hedge Net columns.
Also check what formula the sheet Stats tab uses for net profit.
"""
import json, sys, requests
sys.path.insert(0, '.')
from dashboard.database import get_connection
from utils.data_processor import parse_currency

with get_connection() as conn:
    row = conn.execute('SELECT evaluations FROM clients_data WHERE client_id=?', ('Joe',)).fetchone()
evals = json.loads(row[0])

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                     'Hedge Result 5.1', 'Hedge Result 6.1', 'Hedge Result 7.1']

sum_p1_individual = 0.0
sum_funded_individual = 0.0
sum_hedge_net_p1 = 0.0
sum_hedge_net_funded = 0.0

# Completed group only
for ev in evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    is_p1_fail = sp1 == 'Fail'
    is_funded_ended = sf in ('Fail', 'Completed')
    is_funded_completed = sf == 'Completed'

    p1h_ind = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    fh_ind = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
    hn_p1 = parse_currency(ev.get('Hedge Net'))
    hn_funded = parse_currency(ev.get('Hedge Net.1'))

    if is_p1_fail:
        sum_p1_individual += p1h_ind
        sum_hedge_net_p1 += hn_p1
    if is_funded_ended:
        sum_funded_individual += fh_ind + p1h_ind
        sum_hedge_net_funded += hn_funded + hn_p1

print("Hedging for profitability_completed rows:")
print(f"  Sum of individual P1 hedge cols (P1=Fail):          ${sum_p1_individual:,.2f}")
print(f"  Sum of Hedge Net P1  (P1=Fail):                     ${sum_hedge_net_p1:,.2f}")
print()
print(f"  Sum of individual funded+p1 cols (funded ended):    ${sum_funded_individual:,.2f}")
print(f"  Sum of Hedge Net funded+p1 (funded ended):          ${sum_hedge_net_funded:,.2f}")
print()
total_individual = sum_p1_individual + sum_funded_individual
total_net_cols = sum_hedge_net_p1 + sum_hedge_net_funded
print(f"  Current code TOTAL (individual cols):               ${total_individual:,.2f}")
print(f"  Alternative TOTAL (Hedge Net cols):                 ${total_net_cols:,.2f}")
print(f"  Sheet expected:                                     $-42,160.47")

# Now check the stats tab directly from sheet
print()
print("=== Fetching Stats tab (GID 839895136) CSV ===")
KEY = '1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4'
GID = '839895136'
url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={GID}'
try:
    resp = requests.get(url, timeout=15)
    lines = resp.text.strip().split('\n')
    print(f"Got {len(lines)} lines from Stats tab")
    # Print first 40 lines
    for i, line in enumerate(lines[:40]):
        print(f"  [{i}] {line[:120]}")
except Exception as e:
    print(f"Failed to fetch: {e}")
