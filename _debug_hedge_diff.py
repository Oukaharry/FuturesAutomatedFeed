"""Find which COMPLETED rows have hedging differences between CSV SUMIF and Sheet formulas."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.data_processor import fetch_evaluations

SHEET_URL = "https://docs.google.com/spreadsheets/d/1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs/edit"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def pc(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s == '-' or s.lower() == 'none': return 0.0
    s = s.replace('$', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

# Fetch DB evals (what dashboard uses)
conn = sqlite3.connect(DB_PATH)
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id=?", ('Chris',)).fetchone()
db_evals = json.loads(row[0])
conn.close()

# Fetch Sheet evals + notes (Stats tab)
print("Fetching sheet...")
sh_evals, sh_notes = fetch_evaluations(SHEET_URL)
stats_tab = (sh_notes or {}).get('__stats_tab__', {})
print(f"Stats tab values: {stats_tab}")

# --- Calculate completed hedging the same way calculate_statistics does ---
# Status = Passed/Breached/Closed/Payout → completed
COMPLETED = {'passed', 'breached', 'closed', 'payout'}
P1_COLS = [f'Hedge Result {i}' for i in range(1, 6)]
FD_COLS = [f'Hedge Result {i}.1' for i in range(1, 6)] + ['Hedge Result 6', 'Hedge Result 7']

print("\n=== COMPLETED rows with any hedging value ===")
db_total_p1 = 0.0
db_total_fd = 0.0
sh_total_p1 = 0.0
sh_total_fd = 0.0

for idx in range(min(len(db_evals), len(sh_evals))):
    d = db_evals[idx]
    s = sh_evals[idx]
    rn = idx + 2
    
    # Check completed status - P1 status for P1 hedge, Funded status for funded hedge
    p1_status = str(d.get('Status P1', '') or '').strip().lower()
    f_status = str(d.get('Status', '') or d.get('Status Funded', '') or '').strip().lower()
    
    # P1 hedge columns - count if P1 is completed
    p1_completed = p1_status in COMPLETED
    # Funded hedge columns - count if funded status is completed
    f_completed = f_status in COMPLETED
    
    if p1_completed:
        for c in P1_COLS:
            dv = pc(d.get(c))
            sv = pc(s.get(c))
            db_total_p1 += dv
            sh_total_p1 += sv
            if abs(dv - sv) > 0.005:
                print(f"  Row {rn} [{d.get('Prop Firm')}] P1({p1_status}) {c}: DB={dv:.2f} Sheet={sv:.2f} diff={dv-sv:.2f}")
    
    if f_completed:
        for c in FD_COLS:
            dv = pc(d.get(c))
            sv = pc(s.get(c))
            db_total_fd += dv
            sh_total_fd += sv
            if abs(dv - sv) > 0.005:
                print(f"  Row {rn} [{d.get('Prop Firm')}] FD({f_status}) {c}: DB={dv:.2f} Sheet={sv:.2f} diff={dv-sv:.2f}")

print(f"\n=== Totals ===")
print(f"DB  P1 completed hedge: {db_total_p1:.2f}")
print(f"Sh  P1 completed hedge: {sh_total_p1:.2f}")
print(f"DB  FD completed hedge: {db_total_fd:.2f}")
print(f"Sh  FD completed hedge: {sh_total_fd:.2f}")
print(f"DB  total completed:    {db_total_p1 + db_total_fd:.2f}")
print(f"Sh  total completed:    {sh_total_p1 + sh_total_fd:.2f}")
print(f"Diff:                   {(db_total_p1+db_total_fd)-(sh_total_p1+sh_total_fd):.2f}")

# Now check what calculate_statistics actually computes
print("\n=== What calculate_statistics computes ===")
from utils.data_processor import calculate_statistics
db_stats = calculate_statistics(db_evals, None, None)
sh_stats = calculate_statistics(sh_evals, None, None)
print(f"DB completed hedging (no MT5, no stats override): {db_stats['profitability_completed']['hedging_results']}")
print(f"Sh completed hedging (no MT5, no stats override): {sh_stats['profitability_completed']['hedging_results']}")

# With stats tab override
sh_stats2 = calculate_statistics(sh_evals, None, None, sh_notes)
print(f"Sh completed hedging (with stats override):       {sh_stats2['profitability_completed']['hedging_results']}")
print(f"Stats tab prof_hedging_results value:              {stats_tab.get('prof_hedging_results', 'NOT FOUND')}")
