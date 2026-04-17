"""Recover hedge results from the original 492-eval historical data (100% coverage)
and apply them to matching accounts in the current 633-eval dataset."""
import sqlite3, json
from collections import Counter

db = sqlite3.connect('dashboard/dashboard.db')

# ---- Load current data ----
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])
print(f'Current evals: {len(evals)}')

hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

# ---- Load the best historical data (original 496 with 100%) ----
# Get the latest "100%" version - the 496-eval one from Mar 10
history_rows = db.execute("""
    SELECT id, created_at, evaluations 
    FROM data_history 
    WHERE client_id='Chris' 
    ORDER BY created_at DESC""").fetchall()

best_hist = None
for hid, ts, evals_json in history_rows:
    if not evals_json:
        continue
    try:
        h_evals = json.loads(evals_json)
    except:
        continue
    if not isinstance(h_evals, list):
        continue
    
    # Check if this has good hedge coverage
    filled = 0
    total = len(h_evals) * 6
    real_filled = 0  # Exclude None/null
    for ev in h_evals:
        for hc in hedge_cols:
            v = ev.get(hc)
            if v is not None:
                vs = str(v).strip()
                if vs and vs != 'nan' and vs != 'None':
                    filled += 1
                    real_filled += 1
    
    pct = 100*real_filled/total if total else 0
    print(f'  History {ts}: {len(h_evals)} evals, real hedge fills={real_filled}/{total} ({pct:.1f}%)')
    
    if real_filled > 0 and (best_hist is None or real_filled > best_hist[1]):
        best_hist = (h_evals, real_filled, ts, len(h_evals))

if not best_hist:
    print('ERROR: No historical data with hedge values found')
    exit()

h_evals, h_fills, h_ts, h_count = best_hist
print(f'\nBest history: {h_ts} with {h_count} evals, {h_fills} real hedge fills')

# ---- Build account lookup from history ----
# Try matching on Account #, Account #.1, and other identifiers
h_by_acct = {}    # Account # -> eval dict
h_by_acct1 = {}   # Account #.1 -> eval dict

for ev in h_evals:
    acct = str(ev.get('Account #', '')).strip()
    acct1 = str(ev.get('Account #.1', '')).strip()
    if acct and acct != 'nan':
        h_by_acct[acct] = ev
    if acct1 and acct1 != 'nan':
        h_by_acct1[acct1] = ev

print(f'History accounts by Account #: {len(h_by_acct)}')
print(f'History accounts by Account #.1: {len(h_by_acct1)}')

# ---- Show sample of historical hedge values ----
print(f'\nSample historical hedge values:')
for i, ev in enumerate(h_evals[:10]):
    acct = str(ev.get('Account #', '')).strip()
    vals = {}
    for hc in hedge_cols:
        v = ev.get(hc)
        if v is not None:
            vs = str(v).strip()
            if vs and vs != 'nan' and vs != 'None':
                vals[hc] = vs
    print(f'  [{i}] {acct}: {vals}')

# ---- Apply historical values to current data ----
applied = 0
applied_by_col = Counter()
matched_accounts = 0
unmatched_accounts = []

for i, ev in enumerate(evals):
    acct = str(ev.get('Account #', '')).strip()
    acct1 = str(ev.get('Account #.1', '')).strip()
    
    # Try to find this eval in history
    h_ev = h_by_acct.get(acct) or h_by_acct1.get(acct1) or h_by_acct.get(acct1) or h_by_acct1.get(acct)
    
    if not h_ev:
        # Track for reporting
        missing_any = False
        for hc in hedge_cols:
            v = str(ev.get(hc, '')).strip()
            if not v or v == 'nan':
                missing_any = True
        if missing_any:
            unmatched_accounts.append((i, acct, acct1))
        continue
    
    matched_accounts += 1
    
    # Fill missing hedge values from history
    for hc in hedge_cols:
        current = str(ev.get(hc, '')).strip()
        if current and current != 'nan':
            continue  # Already has a value
        
        h_val = h_ev.get(hc)
        if h_val is not None:
            h_str = str(h_val).strip()
            if h_str and h_str != 'nan' and h_str != 'None':
                evals[i][hc] = h_str
                applied += 1
                applied_by_col[hc] += 1

print(f'\n{"="*80}')
print(f'RECOVERY RESULTS')
print(f'{"="*80}')
print(f'Accounts matched to history: {matched_accounts}')
print(f'Values recovered: {applied}')
print(f'\nBy column:')
for hc in hedge_cols:
    print(f'  {hc:<25} {applied_by_col.get(hc, 0):>5}')

print(f'\nUnmatched accounts still missing hedge data: {len(unmatched_accounts)}')
for i, acct, acct1 in unmatched_accounts[:20]:
    firm = str(evals[i].get('Prop Firm', '')).strip()
    status = str(evals[i].get('Status P1', '')).strip()
    print(f'  Row {i:>3} | {firm:<20} | {acct:<25} | {acct1:<25} | {status}')
if len(unmatched_accounts) > 20:
    print(f'  ... and {len(unmatched_accounts) - 20} more')

# ---- Save if we recovered anything ----
if applied > 0:
    db.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'",
               (json.dumps(evals),))
    db.commit()
    print(f'\n✅ Saved {applied} recovered values to DB')

# ---- Final coverage report ----
print(f'\n{"="*80}')
print(f'FINAL HEDGE RESULT COVERAGE')
print(f'{"="*80}')

for hc in hedge_cols:
    filled = sum(1 for ev in evals 
                 if str(ev.get(hc, '')).strip() and str(ev.get(hc, '')).strip() != 'nan')
    print(f'  {hc:<25} {filled:>4}/{len(evals)} ({100*filled/len(evals):.1f}%)')

# Coverage by status
print(f'\nCoverage by Status:')
for status in ['Pass', 'Fail', 'In Progress', 'Hit TP1']:
    status_evals = [ev for ev in evals if str(ev.get('Status P1', '')).strip() == status]
    if not status_evals:
        continue
    print(f'\n  Status: "{status}" ({len(status_evals)} evals)')
    for hc in hedge_cols:
        filled = sum(1 for ev in status_evals 
                     if str(ev.get(hc, '')).strip() and str(ev.get(hc, '')).strip() != 'nan')
        print(f'    {hc:<25} {filled:>4}/{len(status_evals)} ({100*filled/len(status_evals):.1f}%)')

# ---- Export CSV ----
import csv
all_keys = []
seen = set()
for ev in evals:
    for k in ev.keys():
        if k not in seen:
            all_keys.append(k)
            seen.add(k)

csv_path = r'C:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=all_keys)
    writer.writeheader()
    writer.writerows(evals)

print(f'\n✅ CSV exported to {csv_path}')

db.close()
