"""Fetch Chris sheet and compare with DB to find exact row diffs causing hedging/payout discrepancies."""
import sys, os, json, csv, io, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

from dashboard.database import get_client_data

SHEET_KEY = '1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs'

def pc(val):
    if val is None or val == '' or val == '-': return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace('$','').replace(',','').replace(' ','')
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    try: return float(s)
    except: return 0.0

# Fetch sheet CSV
csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv"
resp = requests.get(csv_url, timeout=30)
reader = csv.DictReader(io.StringIO(resp.text))
sheet_rows = [r for r in reader if r.get('Prop Firm','').strip()]
print(f"Sheet rows: {len(sheet_rows)}")

# DB data
data = get_client_data('Chris')
db_rows = data.get('evaluations', [])
print(f"DB rows: {len(db_rows)}")

P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
F_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
HD_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
PAY_COLS = [f'Payout {i}' for i in range(1, 5)]

# Compare totals from Sheet vs DB
def sum_cols(row, cols):
    return round(sum(pc(row.get(c)) for c in cols), 2)

# Sheet totals
sh_p1 = sum(sum_cols(r, P1_COLS) for r in sheet_rows)
sh_f = sum(sum_cols(r, F_COLS) for r in sheet_rows)
sh_hd = sum(sum_cols(r, HD_COLS) for r in sheet_rows)
sh_pay = sum(sum_cols(r, PAY_COLS) for r in sheet_rows)

db_p1 = sum(sum_cols(r, P1_COLS) for r in db_rows)
db_f = sum(sum_cols(r, F_COLS) for r in db_rows)
db_hd = sum(sum_cols(r, HD_COLS) for r in db_rows)
db_pay = sum(sum_cols(r, PAY_COLS) for r in db_rows)

print(f"\n=== Raw Column Sums ===")
print(f"P1 Hedges:     Sheet={sh_p1:.2f}  DB={db_p1:.2f}  diff={db_p1-sh_p1:.2f}")
print(f"Fund Hedges:   Sheet={sh_f:.2f}  DB={db_f:.2f}  diff={db_f-sh_f:.2f}")
print(f"Hedge Days:    Sheet={sh_hd:.2f}  DB={db_hd:.2f}  diff={db_hd-sh_hd:.2f}")
print(f"Payouts:       Sheet={sh_pay:.2f}  DB={db_pay:.2f}  diff={db_pay-sh_pay:.2f}")
print(f"Total Hedging: Sheet={sh_p1+sh_f:.2f}  DB={db_p1+db_f:.2f}  diff={(db_p1+db_f)-(sh_p1+sh_f):.2f}")

# Row count mismatch
if len(sheet_rows) != len(db_rows):
    print(f"\n⚠️ ROW COUNT MISMATCH: Sheet={len(sheet_rows)} vs DB={len(db_rows)}")

# Compare row-by-row to find where hedging values differ
print(f"\n=== Row-by-row Hedging Value Diffs ===")
max_rows = min(len(sheet_rows), len(db_rows))
total_hedge_diff = 0.0
total_farm_diff = 0.0
total_pay_diff = 0.0
for i in range(max_rows):
    sh = sheet_rows[i]
    db = db_rows[i]
    
    sh_hedge = sum_cols(sh, P1_COLS) + sum_cols(sh, F_COLS)
    db_hedge = sum_cols(db, P1_COLS) + sum_cols(db, F_COLS)
    sh_farm = sum_cols(sh, HD_COLS)
    db_farm = sum_cols(db, HD_COLS)
    sh_payout = sum_cols(sh, PAY_COLS)
    db_payout = sum_cols(db, PAY_COLS)
    
    hdiff = db_hedge - sh_hedge
    fdiff = db_farm - sh_farm
    pdiff = db_payout - sh_payout
    total_hedge_diff += hdiff
    total_farm_diff += fdiff
    total_pay_diff += pdiff
    
    if abs(hdiff) > 0.01 or abs(fdiff) > 0.01 or abs(pdiff) > 0.01:
        firm = db.get('Prop Firm', '?')
        acct = db.get('Account Number', '?')
        status_p1 = db.get('Status P1', '?')
        status_f = db.get('Status') or db.get('Status Funded', '?')
        print(f"  R{i}: {firm}/Acct:{acct} P1={status_p1} F={status_f}")
        if abs(hdiff) > 0.01:
            print(f"       Hedge: DB={db_hedge:.2f} Sheet={sh_hedge:.2f} diff={hdiff:.2f}")
            # Show which specific column differs
            for col in P1_COLS + F_COLS:
                d = pc(db.get(col)) - pc(sh.get(col))
                if abs(d) > 0.01:
                    print(f"         {col}: DB={pc(db.get(col)):.2f} Sheet={pc(sh.get(col)):.2f} diff={d:.2f}")
        if abs(fdiff) > 0.01:
            print(f"       Farm: DB={db_farm:.2f} Sheet={sh_farm:.2f} diff={fdiff:.2f}")
        if abs(pdiff) > 0.01:
            print(f"       Payout: DB={db_payout:.2f} Sheet={sh_payout:.2f} diff={pdiff:.2f}")
            for col in PAY_COLS:
                d = pc(db.get(col)) - pc(sh.get(col))
                if abs(d) > 0.01:
                    print(f"         {col}: DB={pc(db.get(col)):.2f} Sheet={pc(sh.get(col)):.2f} diff={d:.2f}")

# Extra rows
if len(db_rows) > len(sheet_rows):
    print(f"\n=== Extra rows in DB (not in Sheet) ===")
    for i in range(len(sheet_rows), len(db_rows)):
        db = db_rows[i]
        hedge = sum_cols(db, P1_COLS) + sum_cols(db, F_COLS)
        farm = sum_cols(db, HD_COLS)
        pay = sum_cols(db, PAY_COLS)
        if abs(hedge) > 0.01 or abs(farm) > 0.01 or abs(pay) > 0.01:
            print(f"  R{i}: {db.get('Prop Firm','?')} hedge={hedge:.2f} farm={farm:.2f} pay={pay:.2f}")
elif len(sheet_rows) > len(db_rows):
    print(f"\n=== Extra rows in Sheet (not in DB) ===")
    for i in range(len(db_rows), len(sheet_rows)):
        sh = sheet_rows[i]
        hedge = sum_cols(sh, P1_COLS) + sum_cols(sh, F_COLS)
        farm = sum_cols(sh, HD_COLS)
        pay = sum_cols(sh, PAY_COLS)
        if abs(hedge) > 0.01 or abs(farm) > 0.01 or abs(pay) > 0.01:
            print(f"  R{i}: {sh.get('Prop Firm','?')} hedge={hedge:.2f} farm={farm:.2f} pay={pay:.2f}")

print(f"\n=== Row-match totals ===")
print(f"Total hedge diff across matched rows: {total_hedge_diff:.2f}")
print(f"Total farm diff across matched rows: {total_farm_diff:.2f}")
print(f"Total payout diff across matched rows: {total_pay_diff:.2f}")
