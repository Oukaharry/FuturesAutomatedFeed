"""Cross-reference push log with DB/Sheet diffs for the 3 hedging problem rows."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs/edit?usp=sharing'

# Fetch live sheet
result = fetch_evaluations(SHEET_URL)
sheet_rows, _ = result if isinstance(result, tuple) else (result, {})

# DB data
data = get_client_data('Chris')
db_rows = data.get('evaluations', [])

P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
F_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
PAY_COLS = [f'Payout {i}' for i in range(1, 5)]

# The 3 hedging problem rows (0-indexed) identified by comparison
# Push Row #219 = DB[217], Row #340 = DB[338], Row #486 = DB[484]
# Also payout Row #366 = DB[364], farming Row #394 = DB[392]
problem_rows = [
    (217, 219, "MFF V2-1128, Push: CH1→HR1=$-195.82"),
    (338, 340, "Tradeify V2-3458, Push: CH1→HR1=$-194.76"),
    (484, 486, "FundedNext FNFT-86721, Push: CH2→HR2=$-150.25"),
    (364, 366, "TopStep Payouts diff=$2701"),
    (392, 394, "TopStep Farming diff=$18.92"),
]

for idx, sheet_row_num, desc in problem_rows:
    print(f"\n{'='*70}")
    print(f"Row {sheet_row_num} (idx {idx}): {desc}")
    print(f"{'='*70}")
    
    db = db_rows[idx] if idx < len(db_rows) else None
    sh = sheet_rows[idx] if idx < len(sheet_rows) else None
    
    if not db and not sh:
        print("  MISSING!")
        continue
    
    firm = (db or sh).get('Prop Firm', '?')
    sp1_db = db.get('Status P1', '?') if db else '?'
    sf_db = (db.get('Status') or db.get('Status Funded', '?')) if db else '?'
    print(f"  Firm: {firm} | P1={sp1_db} F={sf_db}")
    
    # P1 hedge columns
    print(f"\n  P1 Hedge Columns:")
    for col in P1_COLS:
        db_val = parse_currency(db.get(col)) if db else 0.0
        sh_val = parse_currency(sh.get(col)) if sh else 0.0
        diff = db_val - sh_val
        marker = " ⚠️" if abs(diff) > 0.01 else ""
        print(f"    {col:20s}: DB={db_val:>10.2f}  Sheet={sh_val:>10.2f}  diff={diff:>10.2f}{marker}")
    
    db_p1_total = round(sum(parse_currency(db.get(c)) for c in P1_COLS), 2) if db else 0
    sh_p1_total = round(sum(parse_currency(sh.get(c)) for c in P1_COLS), 2) if sh else 0
    print(f"    {'P1 TOTAL':20s}: DB={db_p1_total:>10.2f}  Sheet={sh_p1_total:>10.2f}  diff={db_p1_total-sh_p1_total:>10.2f}")
    
    # Funded hedge columns
    print(f"\n  Funded Hedge Columns:")
    for col in F_COLS:
        db_val = parse_currency(db.get(col)) if db else 0.0
        sh_val = parse_currency(sh.get(col)) if sh else 0.0
        diff = db_val - sh_val
        marker = " ⚠️" if abs(diff) > 0.01 else ""
        print(f"    {col:20s}: DB={db_val:>10.2f}  Sheet={sh_val:>10.2f}  diff={diff:>10.2f}{marker}")
    
    db_f_total = round(sum(parse_currency(db.get(c)) for c in F_COLS), 2) if db else 0
    sh_f_total = round(sum(parse_currency(sh.get(c)) for c in F_COLS), 2) if sh else 0
    print(f"    {'FUND TOTAL':20s}: DB={db_f_total:>10.2f}  Sheet={sh_f_total:>10.2f}  diff={db_f_total-sh_f_total:>10.2f}")
    
    # Hedge Net columns
    hn_db = parse_currency(db.get('Hedge Net')) if db else 0
    hn_sh = parse_currency(sh.get('Hedge Net')) if sh else 0
    hn1_db = parse_currency(db.get('Hedge Net.1')) if db else 0
    hn1_sh = parse_currency(sh.get('Hedge Net.1')) if sh else 0
    print(f"\n  Hedge Net:       DB={hn_db:>10.2f}  Sheet={hn_sh:>10.2f}")
    print(f"  Hedge Net.1:     DB={hn1_db:>10.2f}  Sheet={hn1_sh:>10.2f}")
    
    # Payouts
    print(f"\n  Payout Columns:")
    for col in PAY_COLS:
        db_val = parse_currency(db.get(col)) if db else 0.0
        sh_val = parse_currency(sh.get(col)) if sh else 0.0
        diff = db_val - sh_val
        marker = " ⚠️" if abs(diff) > 0.01 else ""
        if abs(diff) > 0.01:
            print(f"    {col:20s}: DB={db_val:>10.2f}  Sheet={sh_val:>10.2f}  diff={diff:>10.2f}{marker}")
    
    db_pay = round(sum(parse_currency(db.get(c)) for c in PAY_COLS), 2) if db else 0
    sh_pay = round(sum(parse_currency(sh.get(c)) for c in PAY_COLS), 2) if sh else 0
    if abs(db_pay - sh_pay) > 0.01:
        print(f"    {'PAY TOTAL':20s}: DB={db_pay:>10.2f}  Sheet={sh_pay:>10.2f}  diff={db_pay-sh_pay:>10.2f}")
    
    # Farming (Hedge Day cols)
    HD_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
    db_hd = round(sum(parse_currency(db.get(c)) for c in HD_COLS), 2) if db else 0
    sh_hd = round(sum(parse_currency(sh.get(c)) for c in HD_COLS), 2) if sh else 0
    if abs(db_hd - sh_hd) > 0.01:
        print(f"\n  Farming Total:   DB={db_hd:>10.2f}  Sheet={sh_hd:>10.2f}  diff={db_hd-sh_hd:>10.2f}")
        for i in range(1, 35):
            col = f'Hedge Day {i}'
            dv = parse_currency(db.get(col)) if db else 0
            sv = parse_currency(sh.get(col)) if sh else 0
            if abs(dv - sv) > 0.01:
                print(f"    {col:20s}: DB={dv:>10.2f}  Sheet={sv:>10.2f}  diff={dv-sv:>10.2f} ⚠️")
