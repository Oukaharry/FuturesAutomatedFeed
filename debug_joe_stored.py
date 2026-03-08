"""
Check if Joe's pre-stored statistics in the DB differ from freshly-computed stats.
The dashboard may be serving the stored statistics field directly.
"""
import sys, json
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

from dashboard.database import get_all_clients
from utils.data_processor import calculate_statistics, parse_currency

all_clients = get_all_clients()

joe_data = None
joe_cid = None
for cid, data in all_clients.items():
    if not data:
        continue
    identity = data.get('identity', {}) or {}
    email = identity.get('email', '') or ''
    if cid == 'Joe' or 'joe' in cid.lower() or 'hicken' in email.lower() or 'joehick' in email.lower():
        joe_data = data
        joe_cid = cid
        break

if not joe_data:
    print("ERROR: Joe not found")
    sys.exit(1)

print(f"Found client: '{joe_cid}'")
print(f"Last updated: {joe_data.get('last_updated', 'unknown')}")

# 1. Stored statistics (what the dashboard serves)
stored_stats = joe_data.get('statistics', {})
stored_prof  = stored_stats.get('profitability_completed', {}) if stored_stats else {}

# 2. Freshly computed statistics
db_evals = [ev for ev in (joe_data.get('evaluations') or []) if isinstance(ev, dict)]
fresh_stats = calculate_statistics(db_evals, None, None)
fresh_prof  = fresh_stats['profitability_completed']

print()
print(f"{'Metric':<25} {'STORED (served)':>18} {'FRESH COMPUTE':>16} {'DIFF':>12}")
print("-" * 74)

def diff_line(name, stored, fresh):
    sv = stored if isinstance(stored, (int, float)) else 0.0
    fv = fresh  if isinstance(fresh,  (int, float)) else 0.0
    diff = sv - fv
    flag = " <--- MISMATCH" if abs(diff) > 0.01 else ""
    print(f"{name:<25} {sv:>18,.2f} {fv:>16,.2f} {diff:>12,.2f}{flag}")

diff_line("Challenge Fees",   stored_prof.get('challenge_fees',  0), fresh_prof['challenge_fees'])
diff_line("Hedging Results",  stored_prof.get('hedging_results', 0), fresh_prof['hedging_results'])
diff_line("Farming Results",  stored_prof.get('farming_results', 0), fresh_prof['farming_results'])
diff_line("Payouts",          stored_prof.get('payouts',         0), fresh_prof['payouts'])
diff_line("Activation Fee",   stored_prof.get('activation_fee',  0), fresh_prof['activation_fee'])
diff_line("Net Profit",       stored_prof.get('net_profit',      0), fresh_prof['net_profit'])

print()
print(f"Evals in DB: {len(db_evals)}")

# Also check stored cashflow_inprogress
stored_cash = stored_stats.get('cashflow_inprogress', {}) if stored_stats else {}
fresh_cash  = fresh_stats['cashflow_inprogress']

print()
print(f"{'CASHFLOW IN-PROGRESS':<25} {'STORED':>18} {'FRESH':>16} {'DIFF':>12}")
print("-" * 74)
diff_line("Challenge Fees",   stored_cash.get('challenge_fees',  0), fresh_cash['challenge_fees'])
diff_line("Hedging Results",  stored_cash.get('hedging_results', 0), fresh_cash['hedging_results'])
diff_line("Farming Results",  stored_cash.get('farming_results', 0), fresh_cash['farming_results'])
diff_line("Payouts",          stored_cash.get('payouts',         0), fresh_cash['payouts'])
diff_line("Net Profit",       stored_cash.get('net_profit',      0), fresh_cash['net_profit'])

# Show full stored statistics structure preview
print()
print("=== STORED STATISTICS KEYS ===")
if stored_stats:
    for k in stored_stats:
        val = stored_stats[k]
        if isinstance(val, dict):
            print(f"  {k}: {json.dumps(val)}")
        else:
            print(f"  {k}: {val}")
else:
    print("  (empty / None)")
