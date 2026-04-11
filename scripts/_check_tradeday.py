"""Investigate TradeDay accounts in Chris's evaluations - where did they come from?"""
import json, sqlite3, re

DB_PATH = 'dashboard/dashboard.db'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

# Find all rows with TradeDay firm
print('=== Rows with Prop Firm = TradeDay ===')
td_rows = []
for i, ev in enumerate(evals):
    firm = (ev.get('Prop Firm') or '').strip()
    if firm == 'TradeDay':
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        status = (ev.get('Status P1') or '').strip()
        purchased = (ev.get('Date Purchased') or '').strip()
        td_rows.append(i)
        print(f'  Row {i:>3}: Status={status:<14} Acct#={a:<16} Acct#.1={a1:<16} DatePurchased={purchased}')

print(f'\nTotal TradeDay rows: {len(td_rows)}')

# Find all rows with TDF- prefix accounts (regardless of firm)
print('\n=== Rows with TDF- prefix in any account column ===')
tdf_acct_rows = []
for i, ev in enumerate(evals):
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    if (a.startswith('TDF-') or a1.startswith('TDF-')):
        status = (ev.get('Status P1') or '').strip()
        tdf_acct_rows.append(i)
        if firm != 'TradeDay':
            print(f'  Row {i:>3}: Firm={firm:<22} Status={status:<14} Acct#={a:<16} Acct#.1={a1:<16}')

print(f'Total rows with TDF- accounts: {len(tdf_acct_rows)}')

# Check log data for these TradeDay rows
with open('_log_account_fixes.json', 'r') as f:
    log_data = json.load(f)

row_to_accounts = log_data['row_to_accounts']

print('\n=== Log data for TradeDay rows ===')
for i in td_rows:
    row_key = str(i)
    log_entries = row_to_accounts.get(row_key, [])
    ev = evals[i]
    a = (ev.get('Account #') or '').strip()
    status = (ev.get('Status P1') or '').strip()
    print(f'\n  Row {i} (Status={status}, Acct#={a}):')
    if log_entries:
        for acct, phase in log_entries:
            print(f'    Log: {acct} ({phase})')
    else:
        print(f'    No log entries')

# Check: are these TradeDay accounts appearing in OTHER clients' pushes?
# These might be from another client's concurrent push bleeding into Chris's rows
print('\n=== Checking if TDF accounts belong to other clients ===')
tdf_accounts = set()
for i, ev in enumerate(evals):
    for field in ('Account #', 'Account #.1'):
        val = (ev.get(field) or '').strip()
        if val.startswith('TDF-'):
            tdf_accounts.add(val)

print(f'Unique TDF accounts in Chris data: {sorted(tdf_accounts)}')

# Check if these appear in any other client's data
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT client_id, evaluations FROM clients_data")
all_clients = cur.fetchall()
db.close()

for tdf_acct in sorted(tdf_accounts):
    for client_id, evals_json in all_clients:
        if client_id == 'Chris':
            continue
        client_evals = json.loads(evals_json) if evals_json else []
        for j, cev in enumerate(client_evals):
            for field in ('Account #', 'Account #.1'):
                val = (cev.get(field) or '').strip()
                if val == tdf_acct:
                    firm = (cev.get('Prop Firm') or '').strip()
                    print(f'  {tdf_acct} also in {client_id} row {j} (Firm={firm})')

# Check the original extracted JSON account_maps for these rows  
with open('_chris_ream_extracted.json', 'r') as f:
    jdata = json.load(f)

am = jdata['account_maps']
print('\n=== Original account_maps for TradeDay rows ===')
for i in td_rows:
    maps = am.get(str(i), [])
    if maps:
        print(f'  Row {i}: {maps}')

# Look at the raw log [SESSION] lines to see if TDF sessions appear during Chris pushes
# Check which In Progress TradeDay rows exist
ip_td_rows = [i for i in td_rows if (evals[i].get('Status P1') or '').strip() == 'In Progress']
print(f'\nIn Progress TradeDay rows: {ip_td_rows}')
for i in ip_td_rows:
    ev = evals[i]
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    print(f'  Row {i}: Acct#={a}  Acct#.1={a1}')
