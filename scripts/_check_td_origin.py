"""Check where TradeDay Prop Firm assignments came from. 
Are they from the original sheet or were they set by our fix scripts?

Also check: are the In Progress TradeDay rows (615, 627, 628, 629, 630, 634) legitimate?
"""
import json, sqlite3, csv, re

DB_PATH = 'dashboard/dashboard.db'

# Check data_history for the original sheet import
db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get the sheet import versions
cur.execute("""SELECT version, action, change_description, evaluations, created_at 
    FROM data_history WHERE client_id='Chris' AND action='SHEET_IMPORT' 
    ORDER BY version ASC""")
sheet_imports = cur.fetchall()
print(f'Sheet imports: {len(sheet_imports)}')

# Get the first data_push  
cur.execute("""SELECT version, action, change_description, evaluations, created_at 
    FROM data_history WHERE client_id='Chris' AND action='DATA_PUSH' 
    ORDER BY version ASC LIMIT 1""")
first_push = cur.fetchone()
print(f'First data push: v{first_push[0]} @ {first_push[4]}')

# Check the latest sheet import for TradeDay rows
if sheet_imports:
    latest_import = sheet_imports[-1]
    print(f'\nLatest sheet import: v{latest_import[0]} @ {latest_import[4]}')
    print(f'  Description: {latest_import[2]}')
    
    import_evals = json.loads(latest_import[3]) if latest_import[3] else []
    print(f'  Evaluations: {len(import_evals)}')
    
    # Check TradeDay rows in the import
    td_import = []
    for i, ev in enumerate(import_evals):
        firm = (ev.get('Prop Firm') or '').strip()
        if firm == 'TradeDay':
            a = (ev.get('Account #') or '').strip()
            status = (ev.get('Status P1') or '').strip()
            purchased = (ev.get('Date Purchased') or '').strip()
            td_import.append(i)
    print(f'  TradeDay rows in sheet import: {len(td_import)}')
    
    # Compare with current TradeDay In Progress rows
    # These are the ones from the screenshot: rows ~47-52 in the UI (reversed indexing)
    # Check what those specific rows looked like in the sheet import
    cur_db = sqlite3.connect(DB_PATH)
    cur2 = cur_db.cursor()
    cur2.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
    current_evals = json.loads(cur2.fetchone()[0])
    cur_db.close()
    
    # The screenshot shows rows 47-52 from the bottom (UI counts from bottom)
    # Row 52 = TradeDay TDF-17501, Row 51 = Tradeify TDFY-29973, etc
    # The UI row numbers are display row numbers (reversed from actual index)
    # Total is 656, so display row 52 = index 656-52 = 604
    # Actually the UI shows row # which is the row index in the table
    # Let's find the In Progress TradeDay rows
    ip_td = [(i, ev) for i, ev in enumerate(current_evals) 
             if (ev.get('Prop Firm') or '').strip() == 'TradeDay'
             and (ev.get('Status P1') or '').strip() == 'In Progress']
    
    print(f'\n=== Current In Progress TradeDay rows ===')
    for i, ev in ip_td:
        a = (ev.get('Account #') or '').strip()
        a1 = (ev.get('Account #.1') or '').strip()
        print(f'  Row {i}: Acct#={a}  Acct#.1={a1}')
        
        # What was this row in the sheet import?
        if i < len(import_evals):
            imp = import_evals[i]
            imp_firm = (imp.get('Prop Firm') or '').strip()
            imp_a = (imp.get('Account #') or '').strip()
            imp_status = (imp.get('Status P1') or '').strip()
            print(f'    Sheet import: Firm={imp_firm}  Acct#={imp_a}  Status={imp_status}')
        else:
            print(f'    NOT IN SHEET IMPORT (row {i} > {len(import_evals)})')
    
    # Now check what these rows look like in the FIRST data push
    if first_push:
        push_evals = json.loads(first_push[3]) if first_push[3] else []
        print(f'\n=== First data push had {len(push_evals)} evals ===')
        for i, ev in ip_td:
            if i < len(push_evals):
                pev = push_evals[i]
                p_firm = (pev.get('Prop Firm') or '').strip()
                p_a = (pev.get('Account #') or '').strip()
                p_status = (pev.get('Status P1') or '').strip()
                print(f'  Row {i}: Push Firm={p_firm}  Acct#={p_a}  Status={p_status}')

# Check the REAL original data - from the original dashboard CSV
print('\n=== Original Dashboard CSV ===')
DASH_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
try:
    with open(DASH_CSV, 'r', encoding='utf-8-sig') as f:
        dash_rows = list(csv.DictReader(f))
    
    # Find In Progress TradeDay rows in original CSV
    for i, ev in ip_td:
        if i < len(dash_rows):
            d = dash_rows[i]
            d_firm = (d.get('Prop Firm') or '').strip()
            d_a = (d.get('Account #') or '').strip()
            d_status = (d.get('Status P1') or '').strip()
            print(f'  Row {i}: Orig CSV Firm={d_firm}  Acct#={d_a}  Status={d_status}')
        else:
            print(f'  Row {i}: NOT IN ORIG CSV')
except FileNotFoundError:
    print('  Original CSV not found')

db.close()
