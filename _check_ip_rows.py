"""Check In Progress rows and determine what firm they should actually be.
The theory: these rows were created by CSV import with wrong Prop Firm, then our 
log extraction assigned TDF accounts because we matched prefix to the (wrong) firm."""
import json, sqlite3
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

# All In Progress rows
ip_rows = [(i, ev) for i, ev in enumerate(evals) if (ev.get('Status P1') or '').strip() == 'In Progress']
print(f'Total In Progress rows: {len(ip_rows)}')

# Check firm distribution for In Progress
ip_firms = Counter((ev.get('Prop Firm') or '').strip() for _, ev in ip_rows)
print(f'\nIn Progress firm distribution:')
for f, c in ip_firms.most_common():
    print(f'  {f}: {c}')

# List ALL In Progress rows
print(f'\n=== All In Progress rows ===')
for i, ev in ip_rows:
    firm = (ev.get('Prop Firm') or '').strip()
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    size = (ev.get('Account Size') or '').strip()
    purchased = (ev.get('Date Purchased') or '').strip()
    print(f'  Row {i:>3}: Firm={firm:<22} Size={size:<12} Acct#={a:<18} Acct#.1={a1:<18} Date={purchased}')

# Now check v51 (first CSV import that added these rows) - what were these rows originally?
cur.execute("SELECT evaluations FROM data_history WHERE client_id='Chris' AND version=51")
v51 = json.loads(cur.fetchone()[0])

print(f'\n=== In Progress rows as they appeared in v51 (first CSV import) ===')
for i, ev in ip_rows:
    if i < len(v51):
        v51_ev = v51[i]
        v51_firm = (v51_ev.get('Prop Firm') or '').strip()
        v51_a = (v51_ev.get('Account #') or '').strip()
        v51_status = (v51_ev.get('Status P1') or '').strip()
        if v51_status == 'In Progress':
            print(f'  Row {i:>3}: v51 Firm={v51_firm:<22} Acct={v51_a:<30} Status={v51_status}')
    else:
        print(f'  Row {i:>3}: NOT IN v51')

# Check which firms Chris is ACTUALLY trading (non-In-Progress, recent dates)
print(f'\n=== Recent completed/failed evals (rows 496+, non-In-Progress) ===')
recent_firms = Counter()
for i in range(496, len(evals)):
    ev = evals[i]
    status = (ev.get('Status P1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    if status != 'In Progress':
        recent_firms[firm] += 1
print(f'Firm distribution of post-sheet rows (excluding In Progress):')
for f, c in recent_firms.most_common():
    print(f'  {f}: {c}')

# Check what the In Progress TradeDay rows look like WITHOUT our account fixes
# Look at the log data for these specific rows
with open('_log_account_fixes.json', 'r') as f:
    log_data = json.load(f)

print(f'\n=== Log matches for In Progress TradeDay rows ===')
td_ip = [(i, ev) for i, ev in ip_rows if (ev.get('Prop Firm') or '').strip() == 'TradeDay']
for i, ev in td_ip:
    key = str(i)
    matches = log_data['row_to_accounts'].get(key, [])
    print(f'\n  Row {i}:')
    if matches:
        # Show ALL accounts matched to this row (before filtering)
        firms_seen = Counter()
        for acct, phase in matches:
            prefix = acct.split('-')[0] if '-' in acct else acct[:4]
            firms_seen[prefix] += 1
        for prefix, c in firms_seen.most_common():
            print(f'    {prefix}: {c} matches')
    else:
        print(f'    No log matches')

db.close()
