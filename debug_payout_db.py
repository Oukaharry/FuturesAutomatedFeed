"""Check stored evaluations: status values & payouts to find $6k discrepancy."""
import json, sys
sys.path.insert(0, '.')
from dashboard.database import get_connection
from utils.data_processor import parse_currency

with get_connection() as conn:
    row = conn.execute('SELECT evaluations FROM clients_data WHERE client_id=?', ('Joe',)).fetchone()

evals = json.loads(row[0])
print(f'Total: {len(evals)}')

groups = {}
for ev in evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '') or '').strip()
    payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))
    key = (sp1, sf)
    if key not in groups:
        groups[key] = {'count': 0, 'payouts': 0.0}
    groups[key]['count'] += 1
    groups[key]['payouts'] += payouts

print(f"\n{'P1 Status':<20} {'Funded Status':<20} {'Payouts':>12}  Count")
print("-" * 65)
for (sp1, sf), d in sorted(groups.items(), key=lambda x: -x[1]['payouts']):
    print(f"{sp1:<20} {sf:<20} ${d['payouts']:>10,.2f}  N={d['count']}")

total_funded_ended = sum(d['payouts'] for (sp1, sf), d in groups.items() if sf in ('Fail', 'Completed'))
print(f"\nTotal payouts where Status=Fail or Completed: ${total_funded_ended:,.2f}")
print(f"Expected (sheet):                              $100,189.00")
print(f"Our calculate_statistics gives:                $106,279.10")
print(f"All payouts total:                             ${sum(d['payouts'] for d in groups.values()):,.2f}")

# Show rows that have payouts but are NOT in Fail/Completed funded status
print("\n=== Rows WITH payouts but NOT Status=Fail/Completed ===")
for (sp1, sf), d in sorted(groups.items(), key=lambda x: -x[1]['payouts']):
    if sf not in ('Fail', 'Completed') and d['payouts'] > 0:
        print(f"  P1={sp1}, Status={sf!r}: ${d['payouts']:,.2f}  (N={d['count']})")

# Check if Status key exists at all in DB evals
no_status = sum(1 for ev in evals if 'Status' not in ev)
print(f"\nRows with NO 'Status' key in stored dict: {no_status}/{len(evals)}")
has_status = sum(1 for ev in evals if 'Status' in ev)
print(f"Rows WITH 'Status' key: {has_status}/{len(evals)}")
