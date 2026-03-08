"""
Compare Joe's live Google Sheet profitability vs local DB stored values.
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

from dashboard.database import get_all_clients
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit?usp=sharing"

# --- 1. Fetch LIVE sheet data ---
print("Fetching LIVE sheet data for Joe...")
result = fetch_evaluations(SHEET_URL)
if isinstance(result, tuple):
    live_evals, _ = result
else:
    live_evals = result
print(f"Live sheet rows: {len(live_evals)}")

live_stats = calculate_statistics(live_evals, None, None)
live_prof = live_stats['profitability_completed']

# --- 2. Fetch DB stored data ---
print("\nFetching DB stored data for Joe...")
all_clients = get_all_clients()
joe_data = all_clients.get('Joe') or all_clients.get('joe')

if not joe_data:
    # Try to find by email
    for cid, data in all_clients.items():
        if data:
            identity = data.get('identity', {}) or {}
            email = identity.get('email', '')
            if 'joe' in email.lower() or 'hicken' in email.lower():
                joe_data = data
                print(f"Found Joe as client_id='{cid}'")
                break

if not joe_data:
    print("ERROR: Could not find Joe in DB")
    sys.exit(1)

db_evals = [ev for ev in (joe_data.get('evaluations') or []) if isinstance(ev, dict)]
print(f"DB stored rows: {len(db_evals)}")

db_stats = calculate_statistics(db_evals, None, None)
db_prof = db_stats['profitability_completed']

# --- 3. Compare ---
print()
print(f"{'Metric':<25} {'LIVE SHEET':>14} {'LOCAL DB':>14} {'DIFF':>14}")
print("-" * 70)

def diff_line(name, live, db):
    diff = live - db
    flag = " <--- MISMATCH" if abs(diff) > 0.01 else ""
    print(f"{name:<25} {live:>14,.2f} {db:>14,.2f} {diff:>14,.2f}{flag}")

diff_line("Challenge Fees",   live_prof['challenge_fees'],   db_prof['challenge_fees'])
diff_line("Hedging Results",  live_prof['hedging_results'],  db_prof['hedging_results'])
diff_line("Farming Results",  live_prof['farming_results'],  db_prof['farming_results'])
diff_line("Payouts",          live_prof['payouts'],          db_prof['payouts'])
diff_line("Activation Fee",   live_prof['activation_fee'],   db_prof['activation_fee'])
diff_line("Net Profit",       live_prof['net_profit'],       db_prof['net_profit'])

print()
print(f"Row count delta: Live={len(live_evals)}, DB={len(db_evals)}, Diff={len(live_evals) - len(db_evals)}")

# --- 4. Row-level diff if there's a mismatch ---
if len(live_evals) != len(db_evals):
    print("\n=== ROW COUNT MISMATCH - checking for new/missing rows ===")

    P1_HEDGE_COLS    = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    def row_key(ev):
        acct  = str(ev.get('Account #', '') or ev.get('Account #.1', '') or '').strip()
        firm  = str(ev.get('Prop Firm', '')).strip()
        fee   = str(ev.get('Fee', '')).strip()
        return f"{firm}|{acct}|{fee}"

    live_keys = {row_key(ev): ev for ev in live_evals}
    db_keys   = {row_key(ev): ev for ev in db_evals}

    only_in_live = set(live_keys) - set(db_keys)
    only_in_db   = set(db_keys) - set(live_keys)

    print(f"\nRows ONLY in live sheet (new/not synced): {len(only_in_live)}")
    for k in sorted(only_in_live)[:20]:
        ev = live_keys[k]
        sp1 = ev.get('Status P1', '')
        sf  = ev.get('Status', '')
        fee = parse_currency(ev.get('Fee'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
        print(f"  [{sp1}/{sf}] Fee={fee:.2f}, P1Hedge={p1h:.2f}, FdHedge={fdh:.2f} | key={k[:60]}")

    print(f"\nRows ONLY in DB (deleted from sheet): {len(only_in_db)}")
    for k in sorted(only_in_db)[:20]:
        ev = db_keys[k]
        sp1 = ev.get('Status P1', '')
        sf  = ev.get('Status', '')
        fee = parse_currency(ev.get('Fee'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
        print(f"  [{sp1}/{sf}] Fee={fee:.2f}, P1Hedge={p1h:.2f}, FdHedge={fdh:.2f} | key={k[:60]}")

# --- 5. Field-level diff for matching rows ---
print("\n=== FIELD-LEVEL DIFF (rows in both, values changed) ===")
P1_HEDGE_COLS    = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

def row_key2(ev):
    acct  = str(ev.get('Account #', '') or '').strip()
    firm  = str(ev.get('Prop Firm', '')).strip()
    fee   = str(ev.get('Fee', '')).strip()
    return f"{firm}|{acct}|{fee}"

live_map = {}
for ev in live_evals:
    k = row_key2(ev)
    live_map.setdefault(k, []).append(ev)

db_map = {}
for ev in db_evals:
    k = row_key2(ev)
    db_map.setdefault(k, []).append(ev)

diffs_found = 0
WATCH_COLS = P1_HEDGE_COLS + FUNDED_HEDGE_COLS + [f'Hedge Day {i}' for i in range(1,35)] + \
             ['Fee', 'Status P1', 'Status', 'Payout 1', 'Payout 2', 'Payout 3', 'Payout 4', 'Activation Fee', 'Farming Net']

for k in set(live_map) & set(db_map):
    live_rows = live_map[k]
    db_rows   = db_map[k]
    if len(live_rows) != len(db_rows):
        continue
    for i, (lev, dev) in enumerate(zip(live_rows, db_rows)):
        for col in WATCH_COLS:
            lv = parse_currency(lev.get(col))
            dv = parse_currency(dev.get(col))
            if abs(lv - dv) > 0.01:
                if diffs_found < 50:
                    print(f"  Row '{k[:50]}' col '{col}': LIVE={lv:.2f}, DB={dv:.2f}, diff={lv-dv:.2f}")
                diffs_found += 1

if diffs_found == 0:
    print("  No field-level differences found in matching rows.")
else:
    print(f"\n  Total field differences: {diffs_found}")
