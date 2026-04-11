"""Trace when TradeDay "In Progress" rows were first created in data_history"""
import json, sqlite3

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get ALL versions with eval count
cur.execute("""SELECT version, action, change_description, evaluations, created_at 
    FROM data_history WHERE client_id='Chris' ORDER BY version ASC""")
all_versions = cur.fetchall()

print(f'Total versions: {len(all_versions)}')

# Find when eval count first exceeded 496 and what happened
for v in all_versions:
    ver, action, desc, evals_json, created = v
    if evals_json:
        evals = json.loads(evals_json)
        n = len(evals)
        
        # Count TradeDay In Progress rows
        td_ip = sum(1 for ev in evals 
                    if (ev.get('Prop Firm') or '').strip() == 'TradeDay'
                    and (ev.get('Status P1') or '').strip() == 'In Progress')
        
        total_td = sum(1 for ev in evals 
                       if (ev.get('Prop Firm') or '').strip() == 'TradeDay')
        
        if n > 490 or td_ip > 0:
            print(f'v{ver}: {action} @ {created}  evals={n}  TD total={total_td}  TD InProgress={td_ip}  desc={desc[:80] if desc else ""}')
    else:
        print(f'v{ver}: {action} @ {created}  evals=NULL')

# Look at the version where TradeDay In Progress first appeared
print('\n=== Finding first version with TradeDay In Progress rows ===')
for v in all_versions:
    ver, action, desc, evals_json, created = v
    if evals_json:
        evals = json.loads(evals_json)
        td_ip = [(i, ev) for i, ev in enumerate(evals) 
                 if (ev.get('Prop Firm') or '').strip() == 'TradeDay'
                 and (ev.get('Status P1') or '').strip() == 'In Progress']
        if td_ip:
            print(f'\nFirst found in v{ver} ({action} @ {created}):')
            for i, ev in td_ip[:5]:
                a = (ev.get('Account #') or '').strip()
                print(f'  Row {i}: Acct={a}')
            break

# Now check the dashboard save endpoint - SAVE actions where TradeDay rows were added
print('\n=== SAVE actions that expanded evals count ===')
prev_count = 0
for v in all_versions:
    ver, action, desc, evals_json, created = v
    if evals_json:
        evals = json.loads(evals_json)
        n = len(evals)
        if n > prev_count and action in ('SAVE', 'DASHBOARD_SAVE', 'UPDATE', 'CREATE'):
            # Check what the newly added rows (prev_count..n) have
            new_rows = evals[prev_count:]
            td_new = [(prev_count+j, ev) for j, ev in enumerate(new_rows) 
                      if (ev.get('Prop Firm') or '').strip() == 'TradeDay']
            if td_new:
                print(f'v{ver} ({action} @ {created}): {prev_count}→{n} evals (+{n-prev_count})')
                print(f'  New TradeDay rows: {len(td_new)}')
                for idx, ev in td_new[:3]:
                    a = (ev.get('Account #') or '').strip()
                    s = (ev.get('Status P1') or '').strip()
                    print(f'    Row {idx}: Acct={a} Status={s}')
        prev_count = n

db.close()
