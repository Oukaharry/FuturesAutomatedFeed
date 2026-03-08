"""Resync Nikki's evaluations (and stats) from the Google Sheet.

The DB has stale rows for several Funded Next accounts that have since
progressed through the funded/farming phases.  This replaces the DB's
evaluation list with the current sheet data, then recalculates stats.
"""
import sys, json
sys.path.insert(0, '.')
from dashboard.database import get_connection, get_all_clients
from utils.data_processor import fetch_evaluations, calculate_statistics
from datetime import datetime

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M/edit'

# ── 1. Identify client ────────────────────────────────────────────────────────
all_clients = get_all_clients()
nikki_id = next(
    (cid for cid in all_clients
     if 'nikk' in str(cid).lower()
     or 'nikk' in str(all_clients[cid].get('identity', {}).get('name', '')).lower()),
    None
)
if not nikki_id:
    print("❌  Could not find Nikki in DB.  Clients available:")
    for cid in all_clients:
        print(f"   {cid}  ({all_clients[cid].get('identity',{}).get('name','')})")
    sys.exit(1)

print(f"Client ID: {nikki_id}")
nikki_data = all_clients[nikki_id]

# ── 2. Fetch fresh evaluations from sheet ─────────────────────────────────────
print("Fetching evaluations from sheet…")
result = fetch_evaluations(SHEET_URL)
evals_sheet = result[0]
print(f"  Sheet rows: {len(evals_sheet)}")
print(f"  DB rows:    {len(nikki_data.get('evaluations', []))}")

# ── 3. Recalculate statistics from fresh evals ────────────────────────────────
print("Recalculating statistics…")
new_stats = calculate_statistics(evals_sheet, None, None)

# Print a quick summary to verify
ci = new_stats.get('cashflow_inprogress', {})
cc = new_stats.get('cashflow_completed', {})
print("\n  cashflow_inprogress:")
print(f"    challenge_fees   : ${ci.get('challenge_fees',0):>12,.2f}")
print(f"    hedging_results  : ${ci.get('hedging_results',0):>12,.2f}")
print(f"    farming_results  : ${ci.get('farming_results',0):>12,.2f}")
print(f"    payouts          : ${ci.get('payouts',0):>12,.2f}")
print(f"    net_profit       : ${ci.get('net_profit',0):>12,.2f}")
print("\n  cashflow_completed:")
print(f"    challenge_fees   : ${cc.get('challenge_fees',0):>12,.2f}")
print(f"    hedging_results  : ${cc.get('hedging_results',0):>12,.2f}")
print(f"    farming_results  : ${cc.get('farming_results',0):>12,.2f}")
print(f"    payouts          : ${cc.get('payouts',0):>12,.2f}")
print(f"    net_profit       : ${cc.get('net_profit',0):>12,.2f}")

# ── 4. Confirm before writing ─────────────────────────────────────────────────
print()
answer = input("Write to DB? [y/N] ").strip().lower()
if answer != 'y':
    print("Aborted – no changes made.")
    sys.exit(0)

# ── 5. Update DB ──────────────────────────────────────────────────────────────
now = datetime.now().isoformat()
with get_connection() as conn:
    conn.execute(
        'UPDATE clients_data SET evaluations = ?, statistics = ?, last_updated = ? WHERE client_id = ?',
        (json.dumps(evals_sheet), json.dumps(new_stats), now, nikki_id)
    )
    conn.commit()

print(f"\n✅  DB updated for client '{nikki_id}'  ({now})")
print(f"   Evaluations: {len(evals_sheet)} rows written")
print("   Statistics : recalculated from fresh data")
