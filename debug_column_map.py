"""Check column-letter mapping vs Stats formulas.
Stats B13 hedging: =SUM(Evaluations!I:M) + SUM(Evaluations!T:Z)
Stats B15 payouts: =SUM(AB:AB)+SUM(AD:AD)+SUM(AF:AF)+SUM(AH:AH)
Stats B12 fees: =-SUM(Evaluations!D:D)
"""
import sqlite3, json, sys
sys.path.insert(0, '.')
from utils.data_processor import parse_currency
from decimal import Decimal

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()
evals = json.loads(data['evaluations'])

# Get ordered column names from first row
first = evals[0]
cols = list(first.keys())

def col_letter(idx):
    """Convert 0-based index to Excel column letter."""
    result = ""
    while idx >= 0:
        result = chr(65 + idx % 26) + result
        idx = idx // 26 - 1
    return result

print("=== COLUMN MAPPING ===")
for i, c in enumerate(cols):
    letter = col_letter(i)
    print(f"  {letter:3s} (col {i:2d}): {c}")

# Now check what columns I:M and T:Z actually are
print(f"\n=== SHEET FORMULA COLUMN RANGES ===")
# I=8, J=9, K=10, L=11, M=12 (0-based)
print("I:M (indices 8-12) for P1 hedging:")
for i in range(8, 13):
    if i < len(cols):
        print(f"  {col_letter(i)}: {cols[i]}")

# T=19, U=20, V=21, W=22, X=23, Y=24, Z=25 (0-based)
print("\nT:Z (indices 19-25) for funded hedging:")
for i in range(19, 26):
    if i < len(cols):
        print(f"  {col_letter(i)}: {cols[i]}")

# AB=27, AD=29, AF=31, AH=33 (0-based)
print("\nAB,AD,AF,AH (indices 27,29,31,33) for payouts:")
for idx in [27, 29, 31, 33]:
    if idx < len(cols):
        print(f"  {col_letter(idx)}: {cols[idx]}")

# Now compute sums using the SHEET's column ranges (by position)
print(f"\n=== SUMS BY COLUMN POSITION (matching sheet formulas) ===")

# B12: =-SUM(D:D) -> column index 3
fee_sum = Decimal('0')
for ev in evals:
    val = parse_currency(ev.get(cols[3]))
    fee_sum += Decimal(str(val))
print(f"B12 =-SUM(D:D) = -{fee_sum} = {-fee_sum}")

# B13: =SUM(I:M) + SUM(T:Z)
hedge_p1 = Decimal('0')
for ev in evals:
    for ci in range(8, 13):
        val = parse_currency(ev.get(cols[ci]))
        hedge_p1 += Decimal(str(val))

hedge_funded = Decimal('0')
for ev in evals:
    for ci in range(19, 26):
        val = parse_currency(ev.get(cols[ci]))
        hedge_funded += Decimal(str(val))

print(f"B13 =SUM(I:M)={hedge_p1} + SUM(T:Z)={hedge_funded} = {hedge_p1 + hedge_funded}")
print(f"     Sheet says: -26644.42")

# B15: =SUM(AB:AB)+SUM(AD:AD)+SUM(AF:AF)+SUM(AH:AH)
payout_total = Decimal('0')
payout_cols_idx = [27, 29, 31, 33]
for ci in payout_cols_idx:
    col_sum = Decimal('0')
    for ev in evals:
        val = parse_currency(ev.get(cols[ci]))
        col_sum += Decimal(str(val))
    print(f"  SUM({col_letter(ci)}:{col_letter(ci)}) [{cols[ci]}] = {col_sum}")
    payout_total += col_sum
print(f"B15 total = {payout_total}")
print(f"     Sheet says: 145295.20")

# Now compute using NAMED columns like Python code does
print(f"\n=== SUMS BY NAMED COLUMNS (Python code) ===")
P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

p1_named = Decimal('0')
for ev in evals:
    for c in P1_HEDGE_COLS:
        p1_named += Decimal(str(parse_currency(ev.get(c))))

funded_named = Decimal('0')
for ev in evals:
    for c in FUNDED_HEDGE_COLS:
        funded_named += Decimal(str(parse_currency(ev.get(c))))

print(f"P1 hedges (named):     {p1_named}")
print(f"Funded hedges (named): {funded_named}")
print(f"Total hedges (named):  {p1_named + funded_named}")

PAYOUT_COLS = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']
payout_named = Decimal('0')
for c in PAYOUT_COLS:
    col_sum = Decimal('0')
    for ev in evals:
        col_sum += Decimal(str(parse_currency(ev.get(c))))
    print(f"  {c}: {col_sum}")
    payout_named += col_sum
print(f"Total payouts (named): {payout_named}")
