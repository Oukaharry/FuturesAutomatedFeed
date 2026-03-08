"""Show breakdowns of Nikki's stats by account status so we can compare to the sheet."""
import sys
sys.path.insert(0, '.')
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency, fetch_evaluations

all_clients = get_all_clients()
evals = all_clients['Nikki']['evaluations']
stored = all_clients['Nikki']['statistics']

P1_HEDGE_COLS   = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_HEDGE_COLS   = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
HEDGE_DAY_COLS  = [f'Hedge Day {i}' for i in range(1, 35)]

from collections import Counter

p1_statuses  = Counter(str(ev.get('Status P1','')).strip() for ev in evals)
fd_statuses  = Counter(str(ev.get('Status') or ev.get('Status Funded','')).strip() for ev in evals)

print("P1 Status counts:", dict(p1_statuses))
print("FD Status counts:", dict(fd_statuses))

# Totals per status combo
groups = {}
for ev in evals:
    sp1 = str(ev.get('Status P1','')).strip()
    sfd = str(ev.get('Status') or ev.get('Status Funded','')).strip()
    key = (sp1, sfd)
    if key not in groups:
        groups[key] = dict(count=0, fees=0, p1h=0, fdh=0, fah=0, pay=0)
    g = groups[key]
    g['count'] += 1
    g['fees'] += parse_currency(ev.get('Fee'))
    g['p1h']  += sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    g['fdh']  += sum(parse_currency(ev.get(c)) for c in FD_HEDGE_COLS)
    g['fah']  += sum(parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS)
    g['pay']  += sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1,5))

print(f"\n{'P1':8} {'FD':12} {'Count':>6} {'Fees':>10} {'P1 Hedge':>10} {'FD Hedge':>10} {'FA Hedge':>10} {'Payouts':>10}")
print('-'*80)
for (sp1,sfd), g in sorted(groups.items()):
    print(f"{sp1:8} {sfd:12} {g['count']:>6} {g['fees']:>10,.2f} {g['p1h']:>10,.2f} {g['fdh']:>10,.2f} {g['fah']:>10,.2f} {g['pay']:>10,.2f}")

print(f"\n=== Dashboard currently shows ===")
ci = stored.get('cashflow_inprogress', {})
cc = stored.get('cashflow_completed', {})
print(f"  InProgress  fees={ci.get('challenge_fees',0):,.2f}  hedge={ci.get('hedging_results',0):,.2f}  farm={ci.get('farming_results',0):,.2f}  payouts={ci.get('payouts',0):,.2f}  net={ci.get('net_profit',0):,.2f}")
print(f"  Completed   fees={cc.get('challenge_fees',0):,.2f}  hedge={cc.get('hedging_results',0):,.2f}  farm={cc.get('farming_results',0):,.2f}  payouts={cc.get('payouts',0):,.2f}  net={cc.get('net_profit',0):,.2f}")
