import sys, json, sqlite3
sys.path.insert(0, '.')
from utils.data_processor import calculate_statistics

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT account, statistics, evaluations FROM clients_data WHERE LOWER(client_id) LIKE '%reece%'").fetchone()
if not row:
    print("Reece not found!"); sys.exit(1)
data = {}
for k in row.keys():
    val = row[k]
    if val and isinstance(val, str) and val.strip()[:1] in ('{','['):
        data[k] = json.loads(val)
    else:
        data[k] = val

evals = data.get('evaluations', [])
account = data.get('account')
hr = data.get('statistics', {}).get('hedging_review', {})
hist = hr.get('historical_accounts')

print(f'Historical accounts: {hist}')
print(f'MT5 account keys: {list(account.keys()) if account else None}')

# The mt5_account in DB is a dict; calculate_statistics handles both dict and object
class MT5Account:
    def __init__(self, d):
        for k, v in d.items():
            setattr(self, k, v)

mt5_obj = MT5Account(account) if account and isinstance(account, dict) else account
stats = calculate_statistics(evals, mt5_account=mt5_obj, historical_accounts=hist)
hr_new = stats.get('hedging_review', {})
print(f'\nNEW actual_hedging: {hr_new.get("actual_hedging_results")}')
print(f'NEW discrepancy: {hr_new.get("discrepancy")}')
print(f'NEW sheet_hedging: {hr_new.get("sheet_hedging_results")}')
print(f'NEW current_balance: {hr_new.get("current_balance")}')
print(f'NEW total_deposits: {hr_new.get("total_deposits")}')
print(f'NEW total_withdrawals: {hr_new.get("total_withdrawals")}')

# Show the math
print(f'\n--- Math Verification ---')
dep = hr_new.get('total_deposits', 0)
wth = hr_new.get('total_withdrawals', 0)
bal = hr_new.get('current_balance', 0)
print(f'Current: balance={bal}, deposits={dep}, withdrawals={wth}')
if hist:
    h_dep = sum(float(a.get('deposits', 0) or 0) for a in hist)
    h_wth = sum(float(a.get('withdrawals', 0) or 0) for a in hist)
    h_bal = sum(float(a.get('final_balance', 0) or 0) for a in hist)
    print(f'Historical: deposits={h_dep}, withdrawals={h_wth}, balance={h_bal}')
    print(f'Combined: deposits={dep+h_dep}, withdrawals={wth+h_wth}, balance={bal+h_bal}')
    net = (dep+h_dep) + (wth+h_wth)
    actual = (bal+h_bal) - net
    print(f'net_deposits={net}, actual_hedging={actual}')
    sheet = hr_new.get('sheet_hedging_results', 0)
    print(f'discrepancy = {actual} - ({sheet}) = {actual - sheet}')

conn.close()
