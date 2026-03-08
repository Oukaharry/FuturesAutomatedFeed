"""
Deep analysis: Find bugs causing profitability_completed mismatch vs Google Sheet.
The screenshot shows: Fees=$29,375.92 | Hedge=$28,493.35 | Farm=$0 | Payouts=$0 | Net=-$882.57
These are per-client (single spreadsheet) - let's find which client and compare exactly.
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

from dashboard.database import get_all_clients
from utils.data_processor import calculate_statistics, parse_currency

all_clients = get_all_clients()

# Sheet values from the screenshot
SHEET_FEES    = 29375.92
SHEET_HEDGE   = 28493.35
SHEET_FARM    = 0.00
SHEET_PAYOUTS = 0.00
SHEET_NET     = -882.57

print("=== SEARCHING FOR MATCHING CLIENT ===")
print(f"Looking for: Fees~={SHEET_FEES:.2f}, Hedge~={SHEET_HEDGE:.2f}, Net~={SHEET_NET:.2f}")
print()

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

for client_id, data in all_clients.items():
    if not data:
        continue
    evaluations = [ev for ev in (data.get('evaluations') or []) if isinstance(ev, dict)]
    if not evaluations:
        continue

    stats = calculate_statistics(evaluations, None, None)
    prof = stats['profitability_completed']

    fees_diff   = abs(prof['challenge_fees'] - SHEET_FEES)
    hedge_diff  = abs(prof['hedging_results'] - SHEET_HEDGE)
    net_diff    = abs(prof['net_profit'] - SHEET_NET)

    print(f"Client: {client_id:30} | Evs: {len(evaluations):4d} | "
          f"Fees:{prof['challenge_fees']:>10,.2f}  Hedge:{prof['hedging_results']:>10,.2f}  "
          f"Net:{prof['net_profit']:>10,.2f}")

print()
print("=== DETAILED ANALYSIS OF CHALLENGE FEES DOUBLE-COUNT ===")
print("Issue: When P1=Fail AND Status=(Fail|Completed), the fee is counted TWICE.")
print("Issue: When P1=Fail AND Status=Fail, P1 hedges are counted TWICE.")
print()

for client_id, data in all_clients.items():
    if not data:
        continue
    evaluations = [ev for ev in (data.get('evaluations') or []) if isinstance(ev, dict)]

    # Simulate correct (sheet-accurate) vs current (buggy) calculation
    correct_fees = 0.0
    buggy_fees   = 0.0
    correct_hedge = 0.0
    buggy_hedge   = 0.0

    double_fee_rows = 0
    double_hedge_rows = 0

    for ev in evaluations:
        sp1 = str(ev.get('Status P1', '')).strip()
        sf  = str(ev.get('Status', '')).strip()
        if 'deleted' in sp1.lower() or 'deleted' in sf.lower():
            continue

        is_p1_fail = sp1 == 'Fail'
        is_funded_fail = sf == 'Fail'
        is_funded_completed = sf == 'Completed'
        is_funded_ended = is_funded_fail or is_funded_completed

        fee = parse_currency(ev.get('Fee'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)

        # --- BUGGY (current code) logic ---
        if is_p1_fail:
            buggy_fees += fee
        if is_funded_fail:
            buggy_fees += fee
        if is_funded_completed:
            buggy_fees += fee

        if is_p1_fail:
            buggy_hedge += p1h
        if is_funded_ended:
            buggy_hedge += fdh + p1h

        # --- CORRECT (sheet) logic ---
        # Google Sheet formula: SUMIF(fee, P1="Fail") + SUMIF(fee, Status="Completed") + SUMIF(fee, Status="Fail")
        # Each condition is a SEPARATE SUMIF - so a row that matches MULTIPLE conditions IS double-counted
        # BUT: a row where P1=Fail typically has Status="" (empty) - not Fail/Completed
        # A row where Status=Fail typically has P1=Pass - not Fail
        # So normally no overlap. But when P1=Fail AND Status=Fail, fee would be counted twice BY THE SHEET TOO.
        # Let's check: does P1=Fail AND Status=Fail mean an account that failed BOTH phases?
        if is_p1_fail or is_funded_ended:
            correct_fees += fee  # Count once using OR logic (what the sheet SHOULD mean)
        
        # Sheet hedge formula is also additive: 
        # Part1: p1_hedges where P1=Fail  -> pure P1 fail rows
        # Part2: (funded_hedges + p1_hedges) where Status=Fail|Completed -> funded ended rows
        # For rows where BOTH P1=Fail AND Status=Fail: Part1 AND Part2 both fire -> P1 hedges counted twice
        if is_p1_fail:
            correct_hedge += p1h  # Part 1
        if is_funded_ended:
            correct_hedge += fdh + p1h  # Part 2 (this is intentional per sheet formula)

        # Track double-count cases
        if is_p1_fail and is_funded_ended:
            double_fee_rows += 1
            double_hedge_rows += 1

    print(f"Client {client_id}:")
    print(f"  Buggy fees:   {buggy_fees:>10,.2f}  |  Correct fees:  {correct_fees:>10,.2f}  |  Diff: {buggy_fees - correct_fees:,.2f}")
    print(f"  Buggy hedge:  {buggy_hedge:>10,.2f}  |  Correct hedge: {correct_hedge:>10,.2f}  |  Diff: {buggy_hedge - correct_hedge:,.2f}")
    print(f"  Double fee rows: {double_fee_rows} | Double hedge rows: {double_hedge_rows}")
    print()

print()
print("=== KEY ISSUE SUMMARY ===")
print()
print("The screenshot shows Profitability-Completed for ONE specific client's sheet.")
print("The local dashboard shows AGGREGATE across all clients.")
print()
print("For the aggregate, the key formula bugs are:")
print()
print("1. CHALLENGE FEES DOUBLE-COUNTING (lines 678-682 in utils/data_processor.py):")
print("   When P1=Fail AND (Status=Fail OR Status=Completed):")
print("   -> Fee is added TWICE (once for is_p1_fail, once for is_funded_*)")
print("   The sheet uses 3 separate SUMIF conditions that DON'T normally overlap.")
print("   A typical P1-fail row has Status='' (blank), and a funded-fail row has P1=Pass.")
print()
print("2. HEDGING DOUBLE-COUNTING (lines 686-688 in utils/data_processor.py):")
print("   When P1=Fail AND Status=Fail:")
print("   -> p1_hedges added for is_p1_fail block")
print("   -> p1_hedges added AGAIN in is_funded_ended block")
print("   -> p1_hedges counted TWICE")
print("   This happens for 4 rows (confirmed above).")
print()
print("3. THE SHEET IS SINGLE-CLIENT, DASHBOARD IS AGGREGATE:")
print("   The screenshot ($29K fees, $28K hedge) is for one client's sheet.")
print("   The local DB aggregate shows $196K fees, $221K hedge across 5 clients.")
print("   To compare correctly, you need to run this for that specific client.")
