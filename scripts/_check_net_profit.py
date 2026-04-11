import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
row = conn.execute('SELECT statistics FROM clients_data WHERE client_id=?', ('Chris',)).fetchone()
stats = json.loads(row[0])

hr = stats.get('hedging_review', {})
print('=== Hedging Review ===')
for k, v in hr.items():
    if not k.startswith('_debug'):
        print(f'  {k}: {v}')

discrepancy = hr.get('discrepancy', 0)
print(f'\n  >> discrepancy = actual_hedging - sheet_hedging = {hr.get("actual_hedging_results",0)} - {hr.get("sheet_hedging_results",0)} = {discrepancy}')

print('\n=== Net Profit Breakdown ===')
for section in ['cashflow_inprogress', 'profitability_completed']:
    s = stats[section]
    label = 'In Progress' if 'inprogress' in section else 'Completed'
    print(f'\n--- {label} ---')
    pay = s.get('payouts', 0)
    hedge = s.get('hedging_results', 0)
    farm = s.get('farming_results', 0)
    fees = s.get('challenge_fees', 0)
    net = s.get('net_profit', 0)
    
    print(f'  payouts:         {pay}')
    print(f'  hedging_results: {hedge}')
    print(f'  farming_results: {farm}')
    print(f'  challenge_fees:  -{fees}')
    print(f'  discrepancy:     {discrepancy}')
    print(f'  -------------------------')
    calc = pay + hedge + farm - fees + discrepancy
    print(f'  calculated net:  {calc:.2f}')
    print(f'  stored net:      {net}')
    print(f'  without discr:   {pay + hedge + farm - fees:.2f}')

conn.close()
