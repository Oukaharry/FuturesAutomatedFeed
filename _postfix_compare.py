"""Post-fix comparison: DB evaluations vs live Sheet for Chris — hedging focus."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.data_processor import fetch_evaluations, calculate_statistics

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')
SHEET_URL = "https://docs.google.com/spreadsheets/d/1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs/edit"

def pc(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s == '-' or s.lower() == 'none': return 0.0
    s = s.replace('$', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

# --- DB ---
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT evaluations, deals, account FROM clients_data WHERE client_id=?", ('Chris',)).fetchone()
db_evals = json.loads(row['evaluations'] or '[]')
db_deals = json.loads(row['deals'] or '[]')
db_account = json.loads(row['account'] or '{}')
conn.close()

# --- Sheet ---
print("Fetching live sheet data...")
sh_evals, sh_notes = fetch_evaluations(SHEET_URL)
print(f"DB evaluations: {len(db_evals)}, Sheet evaluations: {len(sh_evals)}")

# --- Stats comparison ---
db_stats = calculate_statistics(db_evals, db_deals if db_deals else None, db_account if db_account else None)
sh_stats = calculate_statistics(sh_evals, None, None, sh_notes if sh_notes else None)

print("\n" + "="*70)
print("STATISTICS COMPARISON")
print("="*70)
for section in ['cashflow_inprogress', 'profitability_completed']:
    db_sec = db_stats.get(section, {})
    sh_sec = sh_stats.get(section, {})
    label = "In Progress" if "inprogress" in section else "Completed"
    print(f"\n--- {label} ---")
    for key in sorted(set(list(db_sec.keys()) + list(sh_sec.keys()))):
        db_v = pc(db_sec.get(key, 0))
        sh_v = pc(sh_sec.get(key, 0))
        diff = db_v - sh_v
        marker = " <<<" if abs(diff) > 0.01 else ""
        print(f"  {key:25s}: DB={db_v:>12.2f}  Sheet={sh_v:>12.2f}  diff={diff:>10.2f}{marker}")

# --- Row-by-row ---
P1 = [f'Hedge Result {i}' for i in range(1, 6)]
FD = [f'Hedge Result {i}.1' for i in range(1, 6)] + ['Hedge Result 6', 'Hedge Result 7']
HD = [f'Hedge Day {i}' for i in range(1, 35)]

print("\n" + "="*70)
print("ROW-BY-ROW DIFFERENCES (DB vs Sheet)")
print("="*70)

mx = min(len(db_evals), len(sh_evals))
tp1 = tfd = tfm = tpy = 0.0
cnt = 0

for i in range(mx):
    d = db_evals[i]; s = sh_evals[i]
    rn = i + 2

    dp1 = sum(pc(d.get(c)) for c in P1)
    sp1 = sum(pc(s.get(c)) for c in P1)
    dfd = sum(pc(d.get(c)) for c in FD)
    sfd = sum(pc(s.get(c)) for c in FD)
    dfm = sum(pc(d.get(c)) for c in HD)
    sfm = sum(pc(s.get(c)) for c in HD)
    dpy = pc(d.get('Payouts'))
    spy = pc(s.get('Payouts'))

    dp = dp1-sp1; dd = dfd-sfd; df = dfm-sfm; dpay = dpy-spy
    if abs(dp)>0.01 or abs(dd)>0.01 or abs(df)>0.01 or abs(dpay)>0.01:
        cnt += 1; tp1+=dp; tfd+=dd; tfm+=df; tpy+=dpay
        firm = d.get('Prop Firm','?')
        acct = d.get('Account #','')
        print(f"\nRow {rn}: {firm} | Acct: {acct}")
        if abs(dp)>0.01:
            print(f"  P1 Hedge:     DB={dp1:>10.2f}  Sheet={sp1:>10.2f}  diff={dp:>10.2f}")
            for c in P1:
                dv=pc(d.get(c)); sv=pc(s.get(c))
                if abs(dv-sv)>0.01: print(f"    {c:20s}: DB={dv:>10.2f} Sheet={sv:>10.2f} diff={dv-sv:>10.2f}")
        if abs(dd)>0.01:
            print(f"  Funded Hedge: DB={dfd:>10.2f}  Sheet={sfd:>10.2f}  diff={dd:>10.2f}")
            for c in FD:
                dv=pc(d.get(c)); sv=pc(s.get(c))
                if abs(dv-sv)>0.01: print(f"    {c:20s}: DB={dv:>10.2f} Sheet={sv:>10.2f} diff={dv-sv:>10.2f}")
        if abs(df)>0.01:
            print(f"  Farming:      DB={dfm:>10.2f}  Sheet={sfm:>10.2f}  diff={df:>10.2f}")
            for c in HD:
                dv=pc(d.get(c)); sv=pc(s.get(c))
                if abs(dv-sv)>0.01: print(f"    {c:20s}: DB={dv:>10.2f} Sheet={sv:>10.2f} diff={dv-sv:>10.2f}")
        if abs(dpay)>0.01:
            print(f"  Payouts:      DB={dpy:>10.2f}  Sheet={spy:>10.2f}  diff={dpay:>10.2f}")

print("\n" + "="*70)
print(f"TOTALS ({cnt} rows with differences)")
print(f"  P1 Hedge diff:      {tp1:>10.2f}")
print(f"  Funded Hedge diff:  {tfd:>10.2f}")
print(f"  Farming diff:       {tfm:>10.2f}")
print(f"  Payouts diff:       {tpy:>10.2f}")
print(f"  Combined Hedge:     {tp1+tfd:>10.2f}")
print("="*70)

if len(db_evals) != len(sh_evals):
    src = db_evals if len(db_evals)>len(sh_evals) else sh_evals
    lbl = "DB" if len(db_evals)>len(sh_evals) else "Sheet"
    print(f"\nRow count mismatch: DB={len(db_evals)} Sheet={len(sh_evals)}. Extra in {lbl}:")
    for j in range(mx, len(src)):
        print(f"  Row {j+2}: {src[j].get('Prop Firm','?')} | {src[j].get('Account #','?')}")
