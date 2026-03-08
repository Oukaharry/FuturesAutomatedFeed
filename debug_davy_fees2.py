"""
Deep dive: exact column names in Davy's evaluations + reproduce data_processor logic exactly.
"""
import sys, io, requests
sys.path.insert(0, '.')
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency, calculate_statistics

all_clients = get_all_clients()
davy_id = None
for cid, data in all_clients.items():
    if 'davy' in str(cid).lower() or 'davy' in str(data.get('client', '')).lower():
        davy_id = cid
        break

if not davy_id:
    print("Davy not found")
    sys.exit(0)

evaluations = all_clients[davy_id].get('evaluations', [])
print(f"Davy id={davy_id}, {len(evaluations)} evaluations\n")

# ── 1. Show what status column names actually exist ──────────────────────────
first_keys = set()
for ev in evaluations[:10]:
    first_keys.update(ev.keys())
status_keys = [k for k in sorted(first_keys) if 'status' in k.lower() or 'fee' in k.lower() or 'Fee' in k]
print("Status/Fee-related column names in evaluations:", status_keys)
print()

# ── 2. Reproduce data_processor exactly ─────────────────────────────────────
P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

total_completed_fees = 0.0
double_counted = []

print(f"{'#':<4} {'Prop Firm':<22} {'Account':<32} {'status_p1':<14} {'status_funded':<14} {'fee':>8} {'act':>8}  {'adds':>5}  {'row_total':>10}")
print("-" * 130)
for i, ev in enumerate(evaluations):
    firm = ev.get('Prop Firm', '?')
    acct = ev.get('Account #', '?')
    fee  = parse_currency(ev.get('Fee'))
    act  = parse_currency(ev.get('Activation Fee'))

    # Exact same logic as data_processor.py
    status_p1     = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '')).strip()

    is_p1_fail          = status_p1 == 'Fail'
    is_funded_fail      = status_funded == 'Fail'
    is_funded_completed = status_funded == 'Completed'
    is_funded_ended     = is_funded_fail or is_funded_completed

    adds = sum([is_p1_fail, is_funded_fail, is_funded_completed])
    row_total = adds * (fee + act)
    total_completed_fees += row_total

    if (fee + act) > 0 and adds > 0:
        flag = f"  *** DOUBLE-COUNTED (x{adds})" if adds > 1 else ""
        print(f"{i:<4} {firm:<22} {acct:<32} {status_p1:<14} {status_funded:<14} {fee:>8.2f} {act:>8.2f}  {adds:>5}  {row_total:>10.2f}{flag}")
        if adds > 1:
            double_counted.append((i, firm, acct, status_p1, status_funded, fee, act, adds))

print(f"\nTotal completed challenge fees (data_processor logic): {total_completed_fees:>12.2f}")
print(f"Sheet shows: -32,357.67  (absolute: 32,357.67)")
print(f"Gap: {total_completed_fees - 32357.67:>+.2f}")

# ── 3. Show double-counted rows ──────────────────────────────────────────────
if double_counted:
    print(f"\n=== Double-counted rows ({len(double_counted)} rows) ===")
    dc_total = sum((adds - 1) * (fee + act) for _, _, _, _, _, fee, act, adds in double_counted)
    for row in double_counted:
        i, firm, acct, sp1, sfund, fee, act, adds = row
        print(f"  [{i}] {firm} / {acct}  p1={sp1}  funded={sfund}  fee={fee:.2f}  act={act:.2f}  x{adds}  extra={(adds-1)*(fee+act):.2f}")
    print(f"  Total extra from double-counting: {dc_total:.2f}")

# ── 4. Correct value (should match sheet) ───────────────────────────────────
correct_total = 0.0
for ev in evaluations:
    fee  = parse_currency(ev.get('Fee'))
    act  = parse_currency(ev.get('Activation Fee'))
    status_p1     = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '')).strip()
    is_p1_fail          = status_p1 == 'Fail'
    is_funded_fail      = status_funded == 'Fail'
    is_funded_completed = status_funded == 'Completed'
    # OR logic: count once if ANY condition matches
    if is_p1_fail or is_funded_fail or is_funded_completed:
        correct_total += fee + act

print(f"\nWith OR logic (should match sheet): {correct_total:>12.2f}")
print(f"Sheet shows:                          32357.67")
print(f"Gap with OR logic: {correct_total - 32357.67:>+.2f}")

# ── 5. Run the actual calculate_statistics and report what it produces ───────
stats = calculate_statistics(evaluations)
pc = stats.get('profitability_completed', {})
ci = stats.get('cashflow_inprogress', {})
print(f"\n=== calculate_statistics output ===")
print(f"Profitability Completed challenge_fees: {pc.get('challenge_fees', 0):>12.2f}")
print(f"  (sheet shows: 32357.67)")
print(f"Cashflow InProgress challenge_fees:     {ci.get('challenge_fees', 0):>12.2f}")
