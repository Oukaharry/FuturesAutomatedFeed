"""
Re-sync Joe's data: fetch live sheet (now with Status Funded fix), recalculate stats, save to DB.
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency
from dashboard.database import get_all_clients, get_connection
import json
from datetime import datetime

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit?usp=sharing"
CLIENT_ID = "Joe"

print("=== Step 1: Fetch live sheet with Status Funded fix ===")
result = fetch_evaluations(SHEET_URL)
live_evals, xlsx_notes = result if isinstance(result, tuple) else (result, {})
print(f"Fetched {len(live_evals)} evaluation rows")

# Check status breakdown
statuses = {}
for ev in live_evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '')).strip()
    key = f"P1={sp1}, Status={sf}"
    statuses[key] = statuses.get(key, 0) + 1

print("Status breakdown after fix:")
for k, v in sorted(statuses.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

# Count rows with payouts now
payout_total = 0.0
for ev in live_evals:
    for i in range(1, 5):
        payout_total += parse_currency(ev.get(f'Payout {i}'))
print(f"\nTotal payouts in fetched data: ${payout_total:,.2f}  (expected ~$100,189)")

print()
print("=== Step 2: Recalculate statistics ===")
stats = calculate_statistics(live_evals, None, None)
prof = stats['profitability_completed']

print(f"Profitability - Completed:")
print(f"  Challenge Fees:  ${prof['challenge_fees']:>12,.2f}  (sheet: $45,242.39)")
print(f"  Hedging Results: ${prof['hedging_results']:>12,.2f}  (sheet: -$42,160.47)")
print(f"  Farming Results: ${prof['farming_results']:>12,.2f}  (sheet: $15,034.28)")
print(f"  Payouts:         ${prof['payouts']:>12,.2f}  (sheet: $100,189.00)")
print(f"  Net Profit:      ${prof['net_profit']:>12,.2f}  (sheet: $27,057.53)")

print()
print("=== Step 3: Save to DB ===")

# Load existing client data so we preserve MT5 fields etc.
all_clients = get_all_clients()
joe_data = all_clients.get(CLIENT_ID)

if not joe_data:
    print(f"ERROR: Client '{CLIENT_ID}' not found in DB")
    sys.exit(1)

# Update evaluations and statistics
import sys, json
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE clients_data SET evaluations = ?, statistics = ?, last_updated = ? WHERE client_id = ?',
        (
            json.dumps(live_evals),
            json.dumps(stats),
            datetime.now().isoformat(),
            CLIENT_ID
        )
    )
    conn.commit()
    print(f"Updated DB for client '{CLIENT_ID}'")
    print(f"Rows affected: {cursor.rowcount}")

print()
print("=== Step 4: Verify DB was updated ===")
all_clients2 = get_all_clients()
joe2 = all_clients2.get(CLIENT_ID)
stored_prof = joe2.get('statistics', {}).get('profitability_completed', {})
print(f"Stored profitability_completed:")
print(f"  Challenge Fees:  ${stored_prof.get('challenge_fees', 0):>12,.2f}")
print(f"  Hedging Results: ${stored_prof.get('hedging_results', 0):>12,.2f}")
print(f"  Farming Results: ${stored_prof.get('farming_results', 0):>12,.2f}")
print(f"  Payouts:         ${stored_prof.get('payouts', 0):>12,.2f}")
print(f"  Net Profit:      ${stored_prof.get('net_profit', 0):>12,.2f}")
