"""
Investigate the $6k payout discrepancy: sheet shows $100,189.00 but code calculates $106,279.10
"""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit?usp=sharing"

result = fetch_evaluations(SHEET_URL)
live_evals, _ = result if isinstance(result, tuple) else (result, {})

print(f"Total rows: {len(live_evals)}\n")
print(f"{'P1 Status':<20} {'F Status':<20} {'Payout Total':>14}  Count")
print("-" * 70)

# Group by status combo and sum payouts
groups = {}
for ev in live_evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '') or ev.get('Status Funded', '')).strip()
    payout = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))
    key = (sp1, sf)
    if key not in groups:
        groups[key] = {'count': 0, 'payouts': 0.0, 'rows': []}
    groups[key]['count'] += 1
    groups[key]['payouts'] += payout
    if payout > 0:
        groups[key]['rows'].append({'payout': payout, 'ev': ev})

for (sp1, sf), data in sorted(groups.items(), key=lambda x: -x[1]['payouts']):
    if data['payouts'] != 0 or data['count'] > 0:
        print(f"{sp1:<20} {sf:<20} ${data['payouts']:>12,.2f}  ({data['count']} rows)")

print()
print("=== Rows that have payouts but are NOT in 'Funded Completed' or 'Funded Fail' ===")
print("(These would be in 'In Progress' but currently coded as Completed)")
total_extra = 0.0
for (sp1, sf), data in groups.items():
    # is_funded_completed = sp1=='Pass' and sf=='Completed'
    # is_funded_fail = sp1=='Pass' and sf=='Fail'
    is_completed_phase = (sp1 == 'Pass' and sf in ('Completed', 'Fail'))
    if not is_completed_phase and data['payouts'] > 0:
        print(f"\n  P1={sp1}, Status={sf}: ${data['payouts']:,.2f} across {len(data['rows'])} payout rows")
        for r in data['rows']:
            print(f"    Payout=${r['payout']:.2f}")
        total_extra += data['payouts']

print(f"\nTotal 'extra' payouts not in completed phase: ${total_extra:,.2f}")
print(f"Expected diff: $106,279.10 - $100,189.00 = $6,090.10")
