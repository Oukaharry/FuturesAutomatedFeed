"""Compare Chris sheet vs DB using proper fetch_evaluations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs/edit?usp=sharing'

# Fetch live sheet
result = fetch_evaluations(SHEET_URL)
if isinstance(result, tuple):
    sheet_rows, xlsx_notes = result
else:
    sheet_rows = result
    xlsx_notes = {}

print(f"Sheet rows: {len(sheet_rows)}")
print(f"XLSX notes keys: {list(xlsx_notes.keys())[:10]}")

# Check stats_tab
stats_tab = xlsx_notes.get('__stats_tab__', {})
if stats_tab:
    print(f"\nStats tab values from XLSX:")
    for k, v in sorted(stats_tab.items()):
        print(f"  {k}: {v}")

# DB data
data = get_client_data('Chris')
db_rows = data.get('evaluations', [])
print(f"\nDB rows: {len(db_rows)}")

P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
F_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
HD_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
PAY_COLS = [f'Payout {i}' for i in range(1, 5)]

def sc(row, cols):
    return round(sum(parse_currency(row.get(c)) for c in cols), 2)

# Compute from sheet data
sh_stats = calculate_statistics(sheet_rows, None, None, xlsx_notes=xlsx_notes)
sh_cf = sh_stats['cashflow_inprogress']
sh_pc = sh_stats['profitability_completed']

# Compute from DB data  
db_stats = calculate_statistics(db_rows, None, None)
db_cf = db_stats['cashflow_inprogress']
db_pc = db_stats['profitability_completed']

print(f"\n=== Stats from Sheet data (with xlsx_notes override) ===")
print(f"IP: fees={sh_cf['challenge_fees']:.2f} hedge={sh_cf['hedging_results']:.2f} farm={sh_cf['farming_results']:.2f} pay={sh_cf['payouts']:.2f}")
print(f"CP: fees={sh_pc['challenge_fees']:.2f} hedge={sh_pc['hedging_results']:.2f} farm={sh_pc['farming_results']:.2f} pay={sh_pc['payouts']:.2f}")

print(f"\n=== Stats from DB data (no override) ===")
print(f"IP: fees={db_cf['challenge_fees']:.2f} hedge={db_cf['hedging_results']:.2f} farm={db_cf['farming_results']:.2f} pay={db_cf['payouts']:.2f}")
print(f"CP: fees={db_pc['challenge_fees']:.2f} hedge={db_pc['hedging_results']:.2f} farm={db_pc['farming_results']:.2f} pay={db_pc['payouts']:.2f}")

# Also compute from Sheet without override
sh_stats2 = calculate_statistics(sheet_rows, None, None)
sh_cf2 = sh_stats2['cashflow_inprogress']
sh_pc2 = sh_stats2['profitability_completed']
print(f"\n=== Stats from Sheet data (NO override) ===")
print(f"IP: fees={sh_cf2['challenge_fees']:.2f} hedge={sh_cf2['hedging_results']:.2f} farm={sh_cf2['farming_results']:.2f} pay={sh_cf2['payouts']:.2f}")
print(f"CP: fees={sh_pc2['challenge_fees']:.2f} hedge={sh_pc2['hedging_results']:.2f} farm={sh_pc2['farming_results']:.2f} pay={sh_pc2['payouts']:.2f}")

print(f"\n=== Diffs: DB vs Sheet (with override) ===")
print(f"IP hedge: {db_cf['hedging_results'] - sh_cf['hedging_results']:.2f}")
print(f"CP hedge: {db_pc['hedging_results'] - sh_pc['hedging_results']:.2f}")  
print(f"IP farm:  {db_cf['farming_results'] - sh_cf['farming_results']:.2f}")
print(f"CP farm:  {db_pc['farming_results'] - sh_pc['farming_results']:.2f}")
print(f"IP pay:   {db_cf['payouts'] - sh_cf['payouts']:.2f}")
print(f"CP pay:   {db_pc['payouts'] - sh_pc['payouts']:.2f}")

print(f"\n=== Diffs: DB vs Sheet (no override) ===")
print(f"IP hedge: {db_cf['hedging_results'] - sh_cf2['hedging_results']:.2f}")
print(f"CP hedge: {db_pc['hedging_results'] - sh_pc2['hedging_results']:.2f}")
print(f"IP farm:  {db_cf['farming_results'] - sh_cf2['farming_results']:.2f}")
print(f"IP pay:   {db_cf['payouts'] - sh_cf2['payouts']:.2f}")

# Row-by-row comparison
if len(sheet_rows) != len(db_rows):
    print(f"\n⚠️ ROW COUNT MISMATCH: Sheet={len(sheet_rows)} DB={len(db_rows)}")

max_rows = min(len(sheet_rows), len(db_rows))
print(f"\n=== Row diffs (showing only rows with hedge/pay/farm diffs) ===")
total_h_diff = 0.0
total_f_diff = 0.0
total_p_diff = 0.0
for i in range(max_rows):
    sh = sheet_rows[i]
    db = db_rows[i]
    
    sh_h = sc(sh, P1_COLS) + sc(sh, F_COLS)
    db_h = sc(db, P1_COLS) + sc(db, F_COLS)
    sh_f = sc(sh, HD_COLS)
    db_f = sc(db, HD_COLS)
    sh_p = sc(sh, PAY_COLS)
    db_p = sc(db, PAY_COLS)
    
    hd = round(db_h - sh_h, 2)
    fd = round(db_f - sh_f, 2)
    pd_ = round(db_p - sh_p, 2)
    total_h_diff += hd
    total_f_diff += fd
    total_p_diff += pd_
    
    if abs(hd) > 0.01 or abs(fd) > 0.5 or abs(pd_) > 0.5:
        firm = db.get('Prop Firm', '?')
        acct = db.get('Account Number', sh.get('Account Number', '?'))
        sp1 = db.get('Status P1','')
        sf = db.get('Status') or db.get('Status Funded','')
        print(f"  R{i}: {firm} | P1={sp1} F={sf}")
        if abs(hd) > 0.01:
            print(f"    Hedge: DB={db_h:.2f} Sheet={sh_h:.2f} diff={hd:.2f}")
        if abs(fd) > 0.5:
            print(f"    Farm:  DB={db_f:.2f} Sheet={sh_f:.2f} diff={fd:.2f}")
        if abs(pd_) > 0.5:
            print(f"    Pay:   DB={db_p:.2f} Sheet={sh_p:.2f} diff={pd_:.2f}")

# Extra rows
if len(sheet_rows) > len(db_rows):
    print(f"\n=== Extra Sheet rows ({len(sheet_rows) - len(db_rows)}) ===")
    for i in range(len(db_rows), len(sheet_rows)):
        sh = sheet_rows[i]
        h = sc(sh, P1_COLS) + sc(sh, F_COLS)
        f = sc(sh, HD_COLS)
        p = sc(sh, PAY_COLS)
        firm = sh.get('Prop Firm','?')
        sp1 = sh.get('Status P1','')
        sf = sh.get('Status') or sh.get('Status Funded','')
        if abs(h) > 0.01 or abs(f) > 0.01 or abs(p) > 0.01:
            print(f"  R{i}: {firm} | P1={sp1} F={sf} | hedge={h:.2f} farm={f:.2f} pay={p:.2f}")
elif len(db_rows) > len(sheet_rows):
    print(f"\n=== Extra DB rows ({len(db_rows) - len(sheet_rows)}) ===")
    for i in range(len(sheet_rows), len(db_rows)):
        db = db_rows[i]
        h = sc(db, P1_COLS) + sc(db, F_COLS)
        f = sc(db, HD_COLS)
        p = sc(db, PAY_COLS)
        firm = db.get('Prop Firm','?')
        sp1 = db.get('Status P1','')
        sf = db.get('Status') or db.get('Status Funded','')
        if abs(h) > 0.01 or abs(f) > 0.01 or abs(p) > 0.01:
            print(f"  R{i}: {firm} | P1={sp1} F={sf} | hedge={h:.2f} farm={f:.2f} pay={p:.2f}")

print(f"\n=== Total row-match diffs ===")
print(f"Hedge: {total_h_diff:.2f}")
print(f"Farm:  {total_f_diff:.2f}")
print(f"Pay:   {total_p_diff:.2f}")
