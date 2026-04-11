"""Debug EV difference between dashboard and Google Sheet for Jie."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

# --- Find Jie in DB ---
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT client_id FROM clients_data").fetchall()
print("All clients:", [r['client_id'] for r in rows])

# Try to find Jie
row = None
for name in ['Jie', 'jie', 'JIE', 'Jiang Quang Huang', 'Jiang']:
    row = conn.execute("SELECT client_id, evaluations, statistics, deals, account FROM clients_data WHERE client_id=?", (name,)).fetchone()
    if row:
        print(f"\nFound client: {row['client_id']}")
        break

if not row:
    row = conn.execute("SELECT client_id, evaluations, statistics, deals, account FROM clients_data WHERE client_id LIKE '%jie%' COLLATE NOCASE").fetchone()
    if row:
        print(f"\nFound client (partial): {row['client_id']}")

if not row:
    print("Client 'Jie' not found in DB!")
    conn.close()
    sys.exit(1)

client_id = row['client_id']
db_evals = json.loads(row['evaluations'] or '[]')
db_stats = json.loads(row['statistics'] or '{}')
db_deals = json.loads(row['deals'] or '[]')
db_account = json.loads(row['account'] or '{}')
conn.close()

print(f"DB evaluations: {len(db_evals)}")
print(f"DB EV: {db_stats.get('expected_value', 'N/A')}")
print(f"DB ev_tracking: {db_stats.get('ev_tracking', {})}")

# --- Fetch Sheet data ---
print("\nFetching sheet data...")
sh_result = fetch_evaluations(SHEET_URL)
if isinstance(sh_result, tuple):
    sh_evals, sh_notes = sh_result
else:
    sh_evals = sh_result
    sh_notes = {}
print(f"Sheet evaluations: {len(sh_evals)}")

# --- Calculate stats from sheet data ---
sh_stats = calculate_statistics(sh_evals, None, None, xlsx_notes=sh_notes)
print(f"Sheet EV (calculated): {sh_stats.get('expected_value', 'N/A')}")
print(f"Sheet ev_tracking: {sh_stats.get('ev_tracking', {})}")

# --- Recalculate from DB evals ---
db_recalc = calculate_statistics(db_evals, db_deals if db_deals else None, db_account if db_account else None)
print(f"\nDB EV (recalculated): {db_recalc.get('expected_value', 'N/A')}")
print(f"DB ev_tracking (recalc): {db_recalc.get('ev_tracking', {})}")

# --- Trace each ended account ---
def trace_ev(evals, label):
    total_net = 0.0
    count = 0
    for idx, ev in enumerate(evals):
        firm = ev.get('Prop Firm', '?')
        status_p1 = str(ev.get('Status P1', '') or '').strip()
        status_f = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip()
        fee = parse_currency(ev.get('Fee'))
        act_fee = parse_currency(ev.get('Activation Fee'))
        p1_hedge_net = sum(parse_currency(ev.get(f'Hedge Result {i}')) for i in range(1, 6))
        fd_hedge_net = sum(parse_currency(ev.get(c)) for c in [f'Hedge Result {i}.1' for i in range(1, 6)] + ['Hedge Result 6', 'Hedge Result 7'])
        payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 5))
        
        ev_net = None
        reason = None
        
        if status_p1 == 'Fail' and status_f not in ('Fail', 'Completed'):
            ev_net = -fee + p1_hedge_net
            reason = "P1 Fail"
        if status_f == 'Fail':
            ev_net = p1_hedge_net + fd_hedge_net + payouts - fee - act_fee
            reason = "Funded Fail"
        if status_f == 'Completed':
            ev_net = p1_hedge_net + fd_hedge_net + payouts - fee - act_fee
            reason = "Funded Completed"
        
        if ev_net is not None:
            total_net += ev_net
            count += 1
            print(f"  Row {idx+2}: {firm:20s} P1={status_p1:6s} F={status_f:10s} ev_net={ev_net:>10.2f}  ({reason}) fee={fee:.0f} act={act_fee:.0f} p1h={p1_hedge_net:.2f} fdh={fd_hedge_net:.2f} pay={payouts:.2f}")
    
    ev_avg = total_net / count if count else 0
    print(f"\n{label} total: {total_net:.2f} / {count} = {ev_avg:.2f}")
    return total_net, count

print("\n" + "="*80)
print("DETAILED EV — Sheet")
print("="*80)
sh_t, sh_c = trace_ev(sh_evals, "Sheet")

print("\n" + "="*80)
print("DETAILED EV — DB")
print("="*80)
db_t, db_c = trace_ev(db_evals, "DB")

# --- Find rows that differ ---
print("\n" + "="*80)
print("ROW DIFFERENCES (DB vs Sheet)")
print("="*80)
mx = min(len(db_evals), len(sh_evals))
for i in range(mx):
    d = db_evals[i]
    s = sh_evals[i]
    dp1 = str(d.get('Status P1', '') or '').strip()
    sp1 = str(s.get('Status P1', '') or '').strip()
    df = str(d.get('Status', '') or d.get('Status Funded', '') or '').strip()
    sf = str(s.get('Status', '') or s.get('Status Funded', '') or '').strip()
    if dp1 != sp1 or df != sf:
        print(f"  Row {i+2}: {d.get('Prop Firm','?')} | DB: P1={dp1} F={df} | Sheet: P1={sp1} F={sf}")

    # Check hedge values
    for c in [f'Hedge Result {j}' for j in range(1,6)] + [f'Hedge Result {j}.1' for j in range(1,6)] + ['Hedge Result 6', 'Hedge Result 7']:
        dv = parse_currency(d.get(c))
        sv = parse_currency(s.get(c))
        if abs(dv - sv) > 0.01:
            print(f"  Row {i+2}: {d.get('Prop Firm','?')} | {c}: DB={dv:.2f} Sheet={sv:.2f}")

if len(db_evals) != len(sh_evals):
    print(f"\n  Row count mismatch: DB={len(db_evals)} Sheet={len(sh_evals)}")

print("\n" + "="*80)
print("SUMMARY")
print(f"  DB stored EV:       {db_stats.get('expected_value', 'N/A')}")
print(f"  DB recalculated EV: {db_recalc.get('expected_value', 'N/A')}")
print(f"  Sheet calculated:   {sh_stats.get('expected_value', 'N/A')}")
print(f"  DB manual trace:    {db_t/db_c if db_c else 0:.2f}")
print(f"  Sheet manual trace: {sh_t/sh_c if sh_c else 0:.2f}")
print("="*80)
