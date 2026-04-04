#!/usr/bin/env python3
"""
Production script: View a client's full evaluation data from the live DB.
Run on PythonAnywhere:  python _view_client_data.py "Aaron"
                        python _view_client_data.py              # lists all clients
"""
import sys, os, json, sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

# ── Column groups (match the 4 tabs in the UI) ──────────────────────────
INFO_COLS = ['Prop Firm', 'Account Size', 'Date Purchased', 'Fee']

EVAL_COLS = [
    'Date Started', 'Date Ended', 'Status P1', 'Account #',
    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
    'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
]

FUNDED_COLS = [
    'Activation Fee', 'Account #.1', 'Date Started.1', 'Date Ended.1', 'Status',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
    'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
    'Hedge Net.1',
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2',
    'Payout 3', 'Date 3', 'Payout 4', 'Date 4',
    'Payout 5', 'Date 5', 'Payout 6', 'Date 6',
]

FARM_COLS = []
for d in range(1, 51):
    FARM_COLS += [f'Prop Day {d}', f'Prop Progress {d}', f'Hedge Day {d}']

ALL_DISPLAY_COLS = INFO_COLS + EVAL_COLS + FUNDED_COLS + FARM_COLS

# ── Helpers ──────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def list_clients():
    conn = get_conn()
    rows = conn.execute(
        "SELECT client_id, last_updated, "
        "json_array_length(evaluations) AS eval_count "
        "FROM clients_data ORDER BY client_id"
    ).fetchall()
    conn.close()
    print(f"\n{'#':<4} {'Client':<30} {'Evals':<8} {'Last Updated'}")
    print('-' * 80)
    for i, r in enumerate(rows, 1):
        print(f"{i:<4} {r['client_id']:<30} {r['eval_count']:<8} {r['last_updated']}")
    print(f"\nTotal: {len(rows)} clients")

def get_evaluations(client_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id = ?",
        (client_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row['evaluations'] or '[]')

def fmt(val):
    """Format a cell value for display."""
    if val is None or val == '' or val == 'null':
        return ''
    if isinstance(val, (int, float)):
        return f"${val:,.2f}" if val != 0 else ''
    return str(val).strip()

# ── Display functions ────────────────────────────────────────────────────
def show_info_eval(evals):
    """Show INFO + EVAL columns (what the first 2 tabs display)."""
    cols = INFO_COLS + EVAL_COLS
    print(f"\n{'='*120}")
    print(f"  INFO + EVAL PHASE  ({len(evals)} evaluations)")
    print(f"{'='*120}")
    
    # Header
    print(f"{'#':<4}", end='')
    for c in cols:
        w = max(len(c), 14)
        print(f" {c:<{w}}", end='')
    print()
    print('-' * 200)
    
    for i, ev in enumerate(evals, 1):
        print(f"{i:<4}", end='')
        for c in cols:
            w = max(len(c), 14)
            print(f" {fmt(ev.get(c, '')):<{w}}", end='')
        print()

def show_funded(evals):
    """Show FUNDED columns."""
    # Only show evals that have funded data
    funded_evals = [ev for ev in evals if any(ev.get(c) for c in FUNDED_COLS)]
    if not funded_evals:
        print("\n  No funded phase data found.")
        return
    
    print(f"\n{'='*120}")
    print(f"  FUNDED PHASE  ({len(funded_evals)} funded evaluations)")
    print(f"{'='*120}")
    
    for i, ev in enumerate(funded_evals, 1):
        idx = evals.index(ev) + 1
        firm = ev.get('Prop Firm', '?')
        acct = ev.get('Account #.1', ev.get('Account #', ''))
        print(f"\n  Row {idx}: {firm} | Funded Acct: {acct}")
        print(f"  {'─'*60}")
        
        for c in FUNDED_COLS:
            val = fmt(ev.get(c, ''))
            if val:
                print(f"    {c:<25} {val}")

def show_farm(evals):
    """Show FARM columns (Hedge Days with data only)."""
    farm_evals = [ev for ev in evals if any(ev.get(f'Hedge Day {d}') for d in range(1, 51))]
    if not farm_evals:
        print("\n  No farming phase data found.")
        return
    
    print(f"\n{'='*120}")
    print(f"  FARMING PHASE  ({len(farm_evals)} farming evaluations)")
    print(f"{'='*120}")
    
    for ev in farm_evals:
        idx = evals.index(ev) + 1
        firm = ev.get('Prop Firm', '?')
        acct = ev.get('Account #.1', ev.get('Account #', ''))
        print(f"\n  Row {idx}: {firm} | Acct: {acct}")
        print(f"  {'─'*60}")
        print(f"  {'Day':<6} {'Prop Day':<16} {'Progress':<16} {'Hedge Day':<16}")
        print(f"  {'─'*54}")
        
        for d in range(1, 51):
            pd = fmt(ev.get(f'Prop Day {d}', ''))
            pp = fmt(ev.get(f'Prop Progress {d}', ''))
            hd = fmt(ev.get(f'Hedge Day {d}', ''))
            if pd or pp or hd:
                print(f"  {d:<6} {pd:<16} {pp:<16} {hd:<16}")

def show_hedge_summary(evals):
    """Show a concise hedge results summary per evaluation."""
    print(f"\n{'='*120}")
    print(f"  HEDGE RESULTS SUMMARY")
    print(f"{'='*120}")
    
    print(f"{'#':<4} {'Prop Firm':<22} {'Status P1':<14} {'HR1-5':<50} {'Net':<12} {'Status FD':<12} {'HR1.1-7':<70} {'Net.1':<12}")
    print('-' * 200)
    
    for i, ev in enumerate(evals, 1):
        firm = str(ev.get('Prop Firm', ''))[:20]
        sp1 = str(ev.get('Status P1', ''))[:12]
        
        # Phase 1 hedge results
        hr = []
        for j in range(1, 6):
            v = ev.get(f'Hedge Result {j}', '')
            hr.append(fmt(v) if v else '.')
        hr_str = ' | '.join(hr)
        hnet = fmt(ev.get('Hedge Net', ''))
        
        # Funded hedge results
        sfd = str(ev.get('Status', ''))[:10]
        fhr = []
        for j in range(1, 6):
            v = ev.get(f'Hedge Result {j}.1', '')
            fhr.append(fmt(v) if v else '.')
        for j in range(6, 8):
            v = ev.get(f'Hedge Result {j}', '')
            fhr.append(fmt(v) if v else '.')
        fhr_str = ' | '.join(fhr)
        fhnet = fmt(ev.get('Hedge Net.1', ''))
        
        print(f"{i:<4} {firm:<22} {sp1:<14} {hr_str:<50} {hnet:<12} {sfd:<12} {fhr_str:<70} {fhnet:<12}")

def show_full_dump(evals, client_id):
    """Dump all non-empty fields per eval as JSON (for recovery/backup)."""
    out = {}
    for i, ev in enumerate(evals):
        clean = {k: v for k, v in ev.items()
                 if v is not None and v != '' and not k.startswith('_')}
        out[f"row_{i+1}"] = clean
    
    fname = f"_dump_{client_id.replace(' ', '_')}.json"
    with open(fname, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Full data dumped to: {fname}")

# ── Main ─────────────────────────────────────────────────────────────────
def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)
    
    # No args → list all clients
    if len(sys.argv) < 2:
        list_clients()
        print("\nUsage: python _view_client_data.py \"Client Name\" [--dump]")
        return
    
    client_id = sys.argv[1]
    dump_mode = '--dump' in sys.argv
    
    evals = get_evaluations(client_id)
    if evals is None:
        print(f"ERROR: Client '{client_id}' not found in DB.")
        # Fuzzy match
        conn = get_conn()
        rows = conn.execute(
            "SELECT client_id FROM clients_data WHERE client_id LIKE ?",
            (f'%{client_id}%',)
        ).fetchall()
        conn.close()
        if rows:
            print("Did you mean:")
            for r in rows:
                print(f"  - {r['client_id']}")
        return
    
    print(f"\n  Client: {client_id}")
    print(f"  Evaluations: {len(evals)}")
    
    if not evals:
        print("  (no evaluation rows)")
        return
    
    # Count active/non-empty
    active = sum(1 for e in evals if e.get('Prop Firm'))
    print(f"  With Prop Firm set: {active}")
    
    show_info_eval(evals)
    show_hedge_summary(evals)
    show_funded(evals)
    show_farm(evals)
    
    if dump_mode:
        show_full_dump(evals, client_id)

if __name__ == '__main__':
    main()
