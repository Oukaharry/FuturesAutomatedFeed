"""Comprehensive EV comparison: DB vs Sheet vs Stats tab for Jie."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

# --- 1. DB State ---
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT evaluations, statistics, deals, account FROM clients_data WHERE client_id=?", ('Jiang Quang Huang',)).fetchone()
if not row:
    print("Client not found in DB!")
    sys.exit(1)
db_evals = json.loads(row['evaluations'] or '[]')
db_stats = json.loads(row['statistics'] or '{}')
db_deals = json.loads(row['deals'] or '[]')
db_account = json.loads(row['account'] or '{}')
conn.close()

print(f"DB evaluations: {len(db_evals)}")
print(f"DB EV stored: {db_stats.get('expected_value', 'N/A')}")
print(f"DB ev_tracking: {db_stats.get('ev_tracking', {})}")

# --- 2. Recalculate stats from DB evals ---
db_recalc = calculate_statistics(db_evals, db_deals if db_deals else None, db_account if db_account else None)
print(f"DB EV recalculated: {db_recalc.get('expected_value', 'N/A')}")

# --- 3. Fetch Sheet data ---
print("\n--- Fetching Sheet data ---")
sh_result = fetch_evaluations(SHEET_URL)
if isinstance(sh_result, tuple):
    sh_evals, sh_notes = sh_result
else:
    sh_evals = sh_result
    sh_notes = {}
print(f"Sheet evaluations: {len(sh_evals)}")

# Check Stats tab override for EV
stats_tab = (sh_notes or {}).get('__stats_tab__', {})
if stats_tab:
    print(f"\nStats tab values found:")
    for k, v in sorted(stats_tab.items()):
        print(f"  {k}: {v}")
else:
    print("\nNo Stats tab values found in xlsx_notes")

# --- 4. Calculate stats from Sheet data ---
sh_stats = calculate_statistics(sh_evals, None, None, xlsx_notes=sh_notes)
print(f"\nSheet EV (calculated by code): {sh_stats.get('expected_value', 'N/A')}")
print(f"Sheet ev_tracking: {sh_stats.get('ev_tracking', {})}")

# --- 5. Trace EV row by row for Sheet ---
print("\n--- EV ROW TRACE (Sheet data) ---")
total_net = 0.0
count = 0
p1_fail_count = 0
funded_fail_count = 0
funded_completed_count = 0
skipped_rows = []

for idx, ev in enumerate(sh_evals):
    firm = ev.get('Prop Firm', '?')
    status_p1 = str(ev.get('Status P1', '') or '').strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '') or '').strip()
    
    fee = parse_currency(ev.get('Fee'))
    activation_fee = parse_currency(ev.get('Activation Fee'))
    p1_hedge_net = parse_currency(ev.get('Hedge Net'))
    funded_hedge_net = parse_currency(ev.get('Hedge Net.1'))
    payouts = round(sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5)), 2)
    
    is_p1_fail = status_p1 == 'Fail'
    is_funded_fail = status_funded == 'Fail'
    is_funded_completed = status_funded == 'Completed'
    
    ev_net = None
    reason = None
    
    # P1 Fail (not funded - must check funded status isn't set)
    if is_p1_fail and not is_funded_fail and not is_funded_completed:
        ev_net = -fee + p1_hedge_net
        reason = "P1 Fail"
        p1_fail_count += 1
    
    if is_funded_fail:
        ev_net = p1_hedge_net + funded_hedge_net + payouts - fee - activation_fee
        reason = "Funded Fail"
        funded_fail_count += 1
        
    if is_funded_completed:
        ev_net = p1_hedge_net + funded_hedge_net + payouts - fee - activation_fee
        reason = "Funded Completed"
        funded_completed_count += 1
    
    if ev_net is not None:
        total_net += ev_net
        count += 1
    else:
        skipped_rows.append((idx+2, firm, status_p1, status_funded))

ev_avg = total_net / count if count else 0
print(f"\nManual trace results:")
print(f"  P1 Fail: {p1_fail_count}")
print(f"  Funded Fail: {funded_fail_count}")
print(f"  Funded Completed: {funded_completed_count}")
print(f"  Total ended: {count}")
print(f"  Total net: {total_net:.2f}")
print(f"  EV (manual): {ev_avg:.2f}")
print(f"  Skipped rows (not ended): {len(skipped_rows)}")
if skipped_rows:
    print(f"  Sample skipped: {skipped_rows[:10]}")

# --- 6. Check if P1=Fail rows that ALSO have funded status are miscounted ---
print("\n--- OVERLAP CHECK: P1 Fail + Funded Status ---")
both_count = 0
for idx, ev in enumerate(sh_evals):
    status_p1 = str(ev.get('Status P1', '') or '').strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '') or '').strip()
    if status_p1 == 'Fail' and status_funded in ('Fail', 'Completed'):
        both_count += 1
        if both_count <= 5:
            print(f"  Row {idx+2}: {ev.get('Prop Firm')} P1={status_p1} F={status_funded}")
print(f"  Total with both P1=Fail AND Funded status: {both_count}")

# --- 7. Summary ---
print("\n" + "="*80)
print("SUMMARY")
print(f"  DB rows:            {len(db_evals)}")  
print(f"  Sheet rows:         {len(sh_evals)}")
print(f"  DB stored EV:       {db_stats.get('expected_value', 'N/A')}")
print(f"  DB recalculated EV: {db_recalc.get('expected_value', 'N/A')}")
print(f"  Sheet code EV:      {sh_stats.get('expected_value', 'N/A')}")
print(f"  Sheet manual EV:    {ev_avg:.2f}")
print(f"  Stats tab EV:       {stats_tab.get('ev', stats_tab.get('expected_value', 'NOT IN STATS TAB'))}")
print("="*80)
