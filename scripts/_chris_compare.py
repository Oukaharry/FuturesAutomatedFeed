"""
Compare: what values did the MT5 push OVERWRITE vs what was already in those cells?
Uses the current DB evaluations (post-push) and the sheet URL to get the original values.
"""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import parse_currency

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", ("Chris",))
row = cur.fetchone()
evals = json.loads(row['evaluations'])
conn.close()

# From server.log - the 16 sessions that were matched during the push:
# Format: (eval_idx, column, value_written, account_info)
updates = [
    (473, 'Hedge Result 1.1', 724.00, 'MFFU-80255 FD1'),
    (474, 'Hedge Result 1.1', 703.04, 'MFFU-80256 FD1'),
    (475, 'Hedge Result 1.1', 726.72, 'MFFU-80257 FD1'),
    (476, 'Hedge Result 1.1', 736.00, 'MFFU-80258 FD1'),
    (487, 'Hedge Result 1', -93.24, 'TDFY-93025 CH1'),
    (488, 'Hedge Result 1', -97.56, 'TDFY-83573 CH1'),
    (447, 'Hedge Result 2.1', 1089.90, 'TDF-59522 FD2'),
    (449, 'Hedge Day 8', -156.28, 'TDF-33548 FA'),
    (484, 'Hedge Result 2', -150.25, 'FNFT-86721 CH2'),  # Note: log says eval_idx=484 but summary says Row 486
    (486, 'Hedge Result 1', -101.38, 'FNFT-35212 CH1'),
    (485, 'Hedge Result 1', -95.57, 'FNFT-71311 CH1'),
    (445, 'Hedge Day 8', -190.11, 'FNFT-76770 FA'),
    (446, 'Hedge Day 7', -178.85, 'FNFT-46494 FA'),
    (338, 'Hedge Result 1', -194.76, 'V2-3458 CH1'),  # log says eval_idx=338 -> Row 340
    (217, 'Hedge Result 1', -195.82, 'V2-1128 CH1'),  # log says eval_idx=217 -> Row 219
    (491, 'Hedge Result 1', -197.48, 'V2-6849 CH1'),  # log says eval_idx=491 -> Row 493
]

print("=" * 100)
print("CELLS UPDATED BY MT5 PUSH - Current values in DB")
print("=" * 100)

total_hedge_pushed = 0.0
total_farm_pushed = 0.0

for idx, col, pushed_val, acct in updates:
    ev = evals[idx]
    current_val = ev.get(col)
    current_parsed = parse_currency(current_val)
    firm = ev.get('Prop Firm', '?')
    acct_num = ev.get('Account #', '?')
    status_p1 = ev.get('Status P1', '?')
    status_fd = ev.get('Status', '?')
    
    # Check if the pushed value matches what's stored now
    match = "MATCH" if abs(current_parsed - pushed_val) < 0.02 else f"DIFF (stored={current_parsed})"
    
    is_farming = 'Day' in col
    if is_farming:
        total_farm_pushed += pushed_val
    else:
        total_hedge_pushed += pushed_val
    
    print(f"  [{idx:3d}] {firm:20s} | {col:20s} | Pushed: ${pushed_val:>10.2f} | DB now: {str(current_val):>12s} ({current_parsed:>10.2f}) | P1={status_p1} FD={status_fd} | {match}")

print(f"\n  Total hedge values pushed: ${total_hedge_pushed:,.2f}")
print(f"  Total farming values pushed: ${total_farm_pushed:,.2f}")
print(f"  Combined: ${total_hedge_pushed + total_farm_pushed:,.2f}")

# Now check: what are ALL the hedge result values for these specific eval rows?
print("\n" + "=" * 100)
print("FULL HEDGE BREAKDOWN FOR UPDATED ROWS")
print("=" * 100)

HEDGE_COLS = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FUNDED_COLS = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
FARM_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

updated_idxs = set(u[0] for u in updates)
for idx in sorted(updated_idxs):
    ev = evals[idx]
    firm = ev.get('Prop Firm', '?')
    acct = ev.get('Account #', '?')
    sp1 = ev.get('Status P1', '?')
    sfd = ev.get('Status', '?')
    
    p1h = sum(parse_currency(ev.get(c)) for c in HEDGE_COLS)
    fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_COLS)
    farm = sum(parse_currency(ev.get(c)) for c in FARM_COLS)
    
    print(f"\n  [{idx}] {firm} | Acct={acct} | P1={sp1} FD={sfd}")
    print(f"    P1 Hedge: ${p1h:,.2f}  Funded Hedge: ${fdh:,.2f}  Farming: ${farm:,.2f}  Total: ${p1h + fdh + farm:,.2f}")
    
    # Show non-zero values
    for c in HEDGE_COLS + FUNDED_COLS:
        v = parse_currency(ev.get(c))
        if v != 0:
            print(f"      {c}: {ev.get(c)} -> ${v:,.2f}")
    for c in FARM_COLS:
        v = parse_currency(ev.get(c))
        if v != 0:
            print(f"      {c}: {ev.get(c)} -> ${v:,.2f}")

# Overall hedging summary
print("\n" + "=" * 100)
print("OVERALL HEDGING SUMMARY (ALL 492 EVALS)")
print("=" * 100)

total_p1h = 0.0
total_fdh = 0.0
total_farm = 0.0
for ev in evals:
    total_p1h += sum(parse_currency(ev.get(c)) for c in HEDGE_COLS)
    total_fdh += sum(parse_currency(ev.get(c)) for c in FUNDED_COLS)
    total_farm += sum(parse_currency(ev.get(c)) for c in FARM_COLS)

print(f"  Total P1 Hedge Results:     ${total_p1h:,.2f}")
print(f"  Total Funded Hedge Results: ${total_fdh:,.2f}")
print(f"  Total Farming (Hedge Days): ${total_farm:,.2f}")
print(f"  Combined Hedge + Farm:      ${total_p1h + total_fdh + total_farm:,.2f}")
print(f"  Stored sheet_hedging_results: -$8,194.79")

# MT5 reconciliation
print("\n" + "=" * 100)
print("MT5 vs SHEET RECONCILIATION")
print("=" * 100)
mt5_deposits = 40029.76
mt5_balance = 26886.29
mt5_actual = mt5_balance - mt5_deposits  # -13143.47
sheet_hedge = total_p1h + total_fdh + total_farm

print(f"  MT5 Deposits:         ${mt5_deposits:,.2f}")
print(f"  MT5 Balance:          ${mt5_balance:,.2f}")
print(f"  MT5 Actual Hedging:   ${mt5_actual:,.2f}  (Balance - Deposits)")
print(f"  Sheet Hedge Total:    ${sheet_hedge:,.2f}")
print(f"  DISCREPANCY:          ${mt5_actual - sheet_hedge:,.2f}")
print(f"")
print(f"  This means the MT5 account lost ${abs(mt5_actual - sheet_hedge):,.2f} MORE than sheet records show.")
print(f"  622 deals in MT5, but only 16 sessions (from 2026-03-06) were matched to eval rows.")
print(f"  The remaining 606 deals' P&L is reflected in MT5 balance but NOT in individual sheet cells.")
