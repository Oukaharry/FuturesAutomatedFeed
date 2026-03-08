"""Investigate (None, Completed) row and farming in HN1."""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M/edit'
evals = fetch_evaluations(SHEET_URL)[0]

P1_HEDGE_COLS = [f'Hedge Result {i}' for i in range(1, 6)]
FD_HEDGE_COLS = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

EXP_COMP = 10288.06

# Print the ('None', 'Completed') row in detail
print("=== ('None', 'Completed') row ===")
for ev in evals:
    sp1 = str(ev.get('Status P1','')).strip()
    sfd = str(ev.get('Status','')).strip()
    if sp1 == 'None' and sfd == 'Completed':
        fee = parse_currency(ev.get('Fee'))
        act = parse_currency(ev.get('Activation Fee'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        fdh = sum(parse_currency(ev.get(c)) for c in FD_HEDGE_COLS)
        fah = sum(parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS)
        pay = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1,5))
        hn1 = parse_currency(ev.get('Hedge Net.1'))
        print(f"  Fee={fee}  Act={act}  p1h={p1h}  fdh={fdh}  fah={fah}  pay={pay}  HN1={hn1}")
        # Manual calc
        manual = pay + fdh + p1h - fee - act + fah
        print(f"  Manual HN1 = {manual:,.2f}")
        for k in list(ev.keys())[:30]:
            print(f"    {k!r}: {ev[k]!r}")
        break

# Now check what calculate_hedge_nets actually outputs for this row
# by looking at what pre-condition it uses
print("\n=== Checking sp1='None' condition in calculate_hedge_nets ===")
# The code checks: if Status P1 not in (None sentinel), NOT "Fail"
# (None in Python is the None type, but 'None' string from sheet is different)
# In the function, there's a condition like: if sp1_status == 'Fail' for hn, else if sfd_status == 'Completed' for hn1
# Let's trace what the code does with sp1='None' (string) and sfd='Completed'
print("In calculate_hedge_nets:")
print("  sp1 = 'None' string from sheet")
print("  sfd = 'Completed'")
print("  is_p1_fail = ('None' == 'Fail') = False")
print("  is_completed = ('Completed' == 'Completed') = True")
print("  is_fail = ('Completed' == 'Fail') = False")
print("  → Should compute HN1 with payouts formula for Completed")

# Big picture: the TOTAL HN+HN1 approach gives 13,015.61 vs expected 10,288.06
# The difference is 2727.55
# Let me look at all possible fee-related things:
total_act_fdc = sum(parse_currency(ev.get('Activation Fee')) for ev in evals 
                    if str(ev.get('Status','')).strip()=='Completed')
total_fee_fdc = sum(parse_currency(ev.get('Fee')) for ev in evals 
                    if str(ev.get('Status','')).strip()=='Completed')
total_fah_fdc = sum(sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1,35))
                    for ev in evals if str(ev.get('Status','')).strip()=='Completed')

print(f"\nFDC totals: fee={total_fee_fdc:,.2f}  act={total_act_fdc:,.2f}  fah={total_fah_fdc:,.2f}")
print(f"  fah_fdc = {total_fah_fdc:,.2f} (should match Farming Results = 3,264.67)")

# Core hypothesis: should fah be in hedging or farming row?
# For fdc rows: hn1 includes fah → this double-counts if farming is separate
# What is 13,015.61 - fah_fdc = 13,015.61 - 3264.67 = 9,750.94?
no_fah_hn1_fdc = 13_015.61 - total_fah_fdc
print(f"\nHN approach - fah_fdc = {no_fah_hn1_fdc:,.2f}  diff = {no_fah_hn1_fdc - EXP_COMP:,.2f}")

# What about fah_fdf?
total_fah_fdf = sum(sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1,35))
                    for ev in evals if str(ev.get('Status','')).strip()=='Fail')
print(f"fah_fdf = {total_fah_fdf:,.2f}")
no_fah_all = 13_015.61 - total_fah_fdc - total_fah_fdf
print(f"HN approach - fah_fdc - fah_fdf = {no_fah_all:,.2f}  diff = {no_fah_all - EXP_COMP:,.2f}")

# HN1 recalc for fdc without fah:
hn_p1f      = sum(parse_currency(ev.get('Hedge Net')) for ev in evals if str(ev.get('Status P1','')).strip()=='Fail')
hn1_fdf     = sum(parse_currency(ev.get('Hedge Net.1')) for ev in evals if str(ev.get('Status','')).strip()=='Fail')
hn1_fdc     = sum(parse_currency(ev.get('Hedge Net.1')) for ev in evals if str(ev.get('Status','')).strip()=='Completed')
print(f"\nStored: hn_p1f={hn_p1f:,.2f} hn1_fdf={hn1_fdf:,.2f} hn1_fdc={hn1_fdc:,.2f}")
print(f"hn1_fdc - fah_fdc = {hn1_fdc - total_fah_fdc:,.2f}")
no_fah = hn_p1f + hn1_fdf + (hn1_fdc - total_fah_fdc)
print(f"hn_p1f + hn1_fdf + (hn1_fdc - fah_fdc) = {no_fah:,.2f}  diff = {no_fah - EXP_COMP:,.2f}")
