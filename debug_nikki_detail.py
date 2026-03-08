"""Detail the specific differing rows for Nikki."""
import sys, json
sys.path.insert(0, '.')
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency, fetch_evaluations

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M/edit'
P1_HEDGE_COLS  = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_HEDGE_COLS  = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1',
                  'Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

evals_db = get_all_clients()['Nikki']['evaluations']
evals_sheet = fetch_evaluations(SHEET_URL)[0]

sheet_by_acct = {}
for ev in evals_sheet:
    a = str(ev.get('Account #','')).strip()
    if a:
        sheet_by_acct[a] = ev

# Rows with significant differences
DIFF_ROWS = [225, 374, 375, 376, 387, 388, 389, 455, 456, 457]  # 0-indexed

def show_row(label, ev):
    acct  = ev.get('Account #','')
    sp1   = ev.get('Status P1','')
    sfd   = ev.get('Status') or ev.get('Status Funded','')
    firm  = ev.get('Prop Firm','')
    fee   = parse_currency(ev.get('Fee'))
    act   = parse_currency(ev.get('Activation Fee'))
    p1h   = [parse_currency(ev.get(c)) for c in P1_HEDGE_COLS]
    fdh   = [parse_currency(ev.get(c)) for c in FD_HEDGE_COLS]
    fah   = [parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS if parse_currency(ev.get(c)) != 0]
    print(f"  {label}:")
    print(f"    Firm={firm}  Acct={acct}  P1={sp1}  Status={sfd}  Fee=${fee:.2f}  Act=${act:.2f}")
    print(f"    P1-hedges  : {p1h[:5]}  → sum={sum(p1h):.2f}")
    print(f"    FD-hedges  : {fdh[:7]}  → sum={sum(fdh):.2f}")
    print(f"    FA-hedges  : {fah[:5]}  → sum={sum(fah):.2f}")
    payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1,5))
    print(f"    Payouts    : ${payouts:.2f}")

for idx in DIFF_ROWS:
    if idx >= len(evals_db):
        continue
    db_ev  = evals_db[idx]
    acct   = str(db_ev.get('Account #','')).strip()
    sht_ev = sheet_by_acct.get(acct)
    print(f"\n{'='*70}")
    print(f"Row {idx+1}  Account: {acct}")
    show_row('DB  ', db_ev)
    if sht_ev:
        show_row('SHEET', sht_ev)
    else:
        print(f"  SHEET: ⚠️  NOT FOUND in sheet")

# Also check for duplicate account numbers in DB vs sheet
print(f"\n\n{'='*70}")
print("Checking for duplicate Account # in DB and Sheet...")

from collections import Counter
db_accts   = [str(ev.get('Account #','')).strip() for ev in evals_db if str(ev.get('Account #','')).strip()]
sht_accts  = [str(ev.get('Account #','')).strip() for ev in evals_sheet if str(ev.get('Account #','')).strip()]

db_dups  = {a: c for a, c in Counter(db_accts).items() if c > 1}
sht_dups = {a: c for a, c in Counter(sht_accts).items() if c > 1}

if db_dups:
    print(f"  DB  duplicate accounts ({len(db_dups)}):")
    for a, c in list(db_dups.items())[:20]:
        print(f"    {a} × {c}")
else:
    print("  DB  : no duplicate accounts")

if sht_dups:
    print(f"  SHEET duplicate accounts ({len(sht_dups)}):")
    for a, c in list(sht_dups.items())[:20]:
        print(f"    {a} × {c}")
else:
    print("  SHEET: no duplicate accounts")
