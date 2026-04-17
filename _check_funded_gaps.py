"""Check what funded-stage accounts are missing hedge results,
and check data_history for any prior versions with more complete data."""
import sqlite3, json
from collections import Counter, defaultdict

db = sqlite3.connect('dashboard/dashboard.db')

# ---- Current data ----
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

# ---- Check data_history for versions with better coverage ----
print('='*80)
print('CHECKING DATA HISTORY VERSIONS')
print('='*80)

history_rows = db.execute("""
    SELECT id, client_id, created_at, length(evaluations) 
    FROM data_history 
    WHERE client_id='Chris' 
    ORDER BY created_at""").fetchall()

print(f'History versions: {len(history_rows)}')

best_coverage = {'version': None, 'coverage': 0, 'evals_count': 0}

for hid, cid, ts, elen in history_rows:
    if not elen or elen < 10:
        continue
    hrow = db.execute("SELECT evaluations FROM data_history WHERE id=?", (hid,)).fetchone()
    if not hrow or not hrow[0]:
        continue
    try:
        h_evals = json.loads(hrow[0])
    except:
        continue
    
    if not isinstance(h_evals, list):
        continue
    
    # Count hedge result coverage
    filled = 0
    total = len(h_evals) * 6
    for ev in h_evals:
        for hc in hedge_cols:
            v = str(ev.get(hc, '')).strip()
            if v and v != 'nan':
                filled += 1
    
    pct = 100*filled/total if total else 0
    print(f'  {ts}  evals={len(h_evals):>4}  hedge filled={filled:>5}/{total:>5} ({pct:.1f}%)')
    
    if filled > best_coverage['coverage']:
        best_coverage = {'version': hid, 'coverage': filled, 'evals_count': len(h_evals), 'ts': ts}

if best_coverage['version']:
    print(f'\nBest historic coverage: {best_coverage["ts"]} with {best_coverage["coverage"]} fills ({best_coverage["evals_count"]} evals)')

# ---- Check which "Pass" status accounts are missing funded-stage hedge results ----
print(f'\n{"="*80}')
print(f'PASS/FUNDED ACCOUNTS MISSING FUNDED HEDGE RESULTS')
print(f'{"="*80}')

funded_cols = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

pass_missing = []
for i, ev in enumerate(evals):
    s1 = str(ev.get('Status P1', '')).strip().lower()
    # "Pass" means they passed the challenge and SHOULD have funded-stage data
    if s1 in ('pass', 'hit tp1'):
        missing_funded = []
        for fc in funded_cols:
            v = str(ev.get(fc, '')).strip()
            if not v or v == 'nan':
                missing_funded.append(fc)
        if missing_funded:
            firm = str(ev.get('Prop Firm', '')).strip()
            acct = str(ev.get('Account #', '')).strip()
            acct1 = str(ev.get('Account #.1', '')).strip()
            hr1 = str(ev.get('Hedge Result 1', '')).strip()
            hr11 = str(ev.get('Hedge Result 1.1', '')).strip()
            pass_missing.append({
                'row': i, 'firm': firm, 'acct': acct, 'acct1': acct1,
                'status': s1, 'missing': missing_funded,
                'hr1': hr1, 'hr11': hr11
            })

print(f'Pass/HitTP1 accounts with missing funded hedge results: {len(pass_missing)}')
for e in pass_missing:
    print(f'  Row {e["row"]:>3} | {e["firm"]:<20} | Acct: {e["acct"]:<15} | Acct.1: {e["acct1"]:<15} | '
          f'HR1={e["hr1"]:<12} HR1.1={e["hr11"]:<12} | Missing: {", ".join(e["missing"])}')

# ---- See if best history version has these values ----
if best_coverage['version']:
    print(f'\n{"="*80}')
    print(f'CHECKING BEST HISTORY VERSION FOR MISSING VALUES')
    print(f'{"="*80}')
    
    hrow = db.execute("SELECT evaluations FROM data_history WHERE id=?", (best_coverage['version'],)).fetchone()
    h_evals = json.loads(hrow[0])
    
    # Build account -> eval map from history
    h_by_acct = {}
    for ev in h_evals:
        acct = str(ev.get('Account #', '')).strip()
        if acct:
            h_by_acct[acct] = ev
    
    recoverable = 0
    for e in pass_missing:
        h_ev = h_by_acct.get(e['acct'])
        if h_ev:
            for mc in e['missing']:
                hv = str(h_ev.get(mc, '')).strip()
                if hv and hv != 'nan':
                    recoverable += 1
                    print(f'  Row {e["row"]} | {e["acct"]} | {mc} = {hv} (in history!)')
    
    if recoverable == 0:
        print('  No additional values found in history versions')

# ---- Overall status breakdown ----
print(f'\n{"="*80}')
print(f'STATUS BREAKDOWN')
print(f'{"="*80}')

status_counts = Counter()
for ev in evals:
    s = str(ev.get('Status P1', '')).strip()
    status_counts[s] += 1

for s, c in status_counts.most_common():
    print(f'  {s or "(empty)":<25} {c:>4}')

# ---- Funded column analysis by status ----
print(f'\n{"="*80}')
print(f'HEDGE RESULT COVERAGE BY STATUS')
print(f'{"="*80}')

for status in ['Pass', 'Fail', 'In Progress', 'Hit TP1', '']:
    status_evals = [ev for ev in evals if str(ev.get('Status P1', '')).strip().lower() == status.lower()]
    if not status_evals:
        continue
    print(f'\n  Status: "{status or "(empty)"}" ({len(status_evals)} evals)')
    for hc in hedge_cols:
        filled = sum(1 for ev in status_evals 
                     if str(ev.get(hc, '')).strip() and str(ev.get(hc, '')).strip() != 'nan')
        print(f'    {hc:<25} {filled:>4}/{len(status_evals)} ({100*filled/len(status_evals):.1f}%)')

db.close()
