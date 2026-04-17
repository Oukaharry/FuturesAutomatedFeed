"""Check hedge result completeness, especially funded stage accounts."""
import sqlite3, json
from collections import Counter, defaultdict

db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0]) if row else []

print(f'Total evals: {len(evals)}')

# Define hedge result columns
hedge_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1']

# Check status columns
status_col = 'Status P1'
status_p2 = 'Status P2'
phase_col = 'Phase'

# Analyze by status
status_counts = Counter()
funded_missing = []
all_missing = []

for i, ev in enumerate(evals):
    s1 = str(ev.get(status_col, '')).strip()
    s2 = str(ev.get(status_p2, '')).strip()
    phase = str(ev.get(phase_col, '')).strip()
    acct = str(ev.get('Account #', '')).strip()
    acct1 = str(ev.get('Account #.1', '')).strip()
    firm = str(ev.get('Prop Firm', '')).strip()
    
    # Check which hedge results are populated
    missing = []
    populated = []
    for hc in hedge_cols:
        val = str(ev.get(hc, '')).strip()
        if val and val != 'nan' and val != '':
            populated.append(hc)
        else:
            missing.append(hc)
    
    is_funded = ('funded' in s1.lower() or 'funded' in s2.lower() or 
                 'funded' in phase.lower() or 'phase 2' in s1.lower() or
                 'phase 2' in phase.lower() or 'p2' in s1.lower())
    
    if missing:
        entry = {
            'row': i, 'acct': acct, 'acct1': acct1, 'firm': firm,
            'status_p1': s1, 'status_p2': s2, 'phase': phase,
            'missing': missing, 'populated': populated,
            'is_funded': is_funded
        }
        all_missing.append(entry)
        if is_funded:
            funded_missing.append(entry)

# Summary
print(f'\nRows with ANY missing hedge result: {len(all_missing)}/{len(evals)}')
print(f'Rows with ALL hedge results filled: {len(evals) - len(all_missing)}/{len(evals)}')

# Break down by how many are missing
missing_count_dist = Counter(len(e['missing']) for e in all_missing)
print(f'\nMissing hedge result distribution:')
for n in sorted(missing_count_dist.keys()):
    print(f'  {n} missing: {missing_count_dist[n]} rows')

# Funded stage specifically
print(f'\n{"="*80}')
print(f'FUNDED STAGE - MISSING HEDGE RESULTS ({len(funded_missing)} rows)')
print(f'{"="*80}')

for e in funded_missing:
    print(f'  Row {e["row"]:>3} | {e["firm"]:<20} | Acct: {e["acct"]:<15} | '
          f'Status: {e["status_p1"]:<20} | Phase: {e["phase"]:<10} | '
          f'Missing: {", ".join(e["missing"])}')

# Check by firm
print(f'\n{"="*80}')
print(f'MISSING HEDGE RESULTS BY FIRM')
print(f'{"="*80}')

firm_stats = defaultdict(lambda: {'total': 0, 'missing_any': 0, 'funded_missing': 0})
for i, ev in enumerate(evals):
    firm = str(ev.get('Prop Firm', '')).strip()
    firm_stats[firm]['total'] += 1

for e in all_missing:
    firm_stats[e['firm']]['missing_any'] += 1

for e in funded_missing:
    firm_stats[e['firm']]['funded_missing'] += 1

for firm in sorted(firm_stats.keys()):
    s = firm_stats[firm]
    print(f'  {firm:<25} Total: {s["total"]:>4}  Missing Any: {s["missing_any"]:>4}  Funded Missing: {s["funded_missing"]:>4}')

# Show ALL rows missing hedge results (non-funded too) grouped by status
print(f'\n{"="*80}')
print(f'ALL MISSING BY STATUS')
print(f'{"="*80}')

by_status = defaultdict(list)
for e in all_missing:
    by_status[e['status_p1']].append(e)

for status in sorted(by_status.keys(), key=lambda s: -len(by_status[s])):
    rows = by_status[status]
    print(f'\n  Status: "{status}" ({len(rows)} rows)')
    for e in rows[:5]:
        print(f'    Row {e["row"]:>3} | {e["firm"]:<20} | Missing: {", ".join(e["missing"])}')
    if len(rows) > 5:
        print(f'    ... and {len(rows)-5} more')

# Also check what hedge result values look like in the logs vs DB
print(f'\n{"="*80}')
print(f'SAMPLE HEDGE RESULT VALUES (populated rows)')
print(f'{"="*80}')

for i, ev in enumerate(evals[:20]):
    vals = {}
    for hc in hedge_cols:
        v = str(ev.get(hc, '')).strip()
        if v and v != 'nan':
            vals[hc] = v
    if vals:
        print(f'  Row {i}: {vals}')

db.close()
