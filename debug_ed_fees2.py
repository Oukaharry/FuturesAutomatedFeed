"""
Deep dive: Ed's cashflow_inprogress challenge fees.
Sheet shows $100,687.80, DB computes $98,105.80. Diff = $2,582.00 (= activation fee total!)
Also check P1=None rows and what the sheet formula includes.
"""
import sys, json
sys.path.insert(0, '.')
from dashboard.database import get_connection
from utils.data_processor import parse_currency

with get_connection() as conn:
    row = conn.execute('SELECT evaluations, statistics FROM clients_data WHERE client_id=?', ('Ed',)).fetchone()

evals = json.loads(row[0])
stats = json.loads(row[1])

ci = stats['cashflow_inprogress']
print(f"DB cashflow_inprogress challenge_fees: ${ci['challenge_fees']:,.2f}")
print(f"DB cashflow_inprogress activation_fee: ${ci.get('activation_fee',0):,.2f}")
print(f"Sheet In Progress challenge_fees:      $100,687.80")
print(f"Difference:                            ${100687.80 - ci['challenge_fees']:,.2f}")
print(f"Total activation fees:                 ${ci.get('activation_fee',0):,.2f}")
print()

# Check: does diff == activation_fee?
diff = 100687.80 - ci['challenge_fees']
act = ci.get('activation_fee', 0)
print(f"diff == activation_fee? {abs(diff - act) < 1.0} (diff={diff:.2f}, act={act:.2f})")
print()

# Also check P1=None rows - are these the issue?
print("=== P1=None or empty rows ===")
for ev in evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    if sp1 in ('None', '', 'none'):
        sf = str(ev.get('Status', '') or '').strip()
        fee = parse_currency(ev.get('Fee'))
        act_fee = parse_currency(ev.get('Activation Fee'))
        firm = ev.get('Prop Firm', '')
        acct = ev.get('Account #', '')
        print(f"  P1={sp1!r} Status={sf!r} Fee=${fee:.2f} Act=${act_fee:.2f} Firm={firm} Acct={acct}")

print()
# Check: sheet formula for cashflow inprogress = -SUM(all fees) - SUM(all activation fees)?
total_fee_all = sum(parse_currency(ev.get('Fee')) for ev in evals)
total_act_all = sum(parse_currency(ev.get('Activation Fee')) for ev in evals)
total_combined = total_fee_all + total_act_all
print(f"Sum of ALL fees:             ${total_fee_all:,.2f}")
print(f"Sum of ALL activation fees:  ${total_act_all:,.2f}")
print(f"Combined (fee + act):        ${total_combined:,.2f}")
print(f"Sheet In Progress:           $100,687.80")
print(f"Matches combined?            {abs(total_combined - 100687.80) < 1.0}")
