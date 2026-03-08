"""Deep precision debug: check every hedge and payout value for precision issues."""
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

# Google Sheets uses 15 significant digits internally (IEEE 754 double precision)
# CSV export may truncate. Let's check for values that lose precision.

P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                     'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
ALL_HEDGE_COLS = P1_HEDGE_COLS + FUNDED_HEDGE_COLS

# Sum each column independently (like the sheet does)
col_sums = {}
for col in ALL_HEDGE_COLS:
    col_sums[col] = Decimal('0')
    for ev in evals:
        raw = ev.get(col)
        val = parse_currency(raw)
        col_sums[col] += Decimal(str(val))

print("=== PER-COLUMN HEDGE SUMS (Decimal precision) ===")
total_hedge = Decimal('0')
for col in ALL_HEDGE_COLS:
    print(f"  {col:25s}: {col_sums[col]:>15}")
    total_hedge += col_sums[col]
print(f"  {'TOTAL':25s}: {total_hedge:>15}")
print(f"  Float total:              {float(total_hedge)}")
print(f"  Expected (sheet):         -26644.42")

# Now check payouts the same way
payout_cols = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']
payout_sums = {}
total_payout = Decimal('0')
for col in payout_cols:
    payout_sums[col] = Decimal('0')
    for ev in evals:
        raw = ev.get(col)
        val = parse_currency(raw)
        payout_sums[col] += Decimal(str(val))
    total_payout += payout_sums[col]

print(f"\n=== PER-COLUMN PAYOUT SUMS ===")
for col in payout_cols:
    print(f"  {col:15s}: {payout_sums[col]:>15}")
print(f"  {'TOTAL':15s}: {total_payout:>15}")
print(f"  Expected (sheet): 145295.20")

# Check for text values in hedge columns that sheets might interpret as numbers
print(f"\n=== HEDGE VALUES THAT MIGHT DIFFER IN SHEET ===")
for i, ev in enumerate(evals):
    for col in ALL_HEDGE_COLS:
        raw = ev.get(col)
        if raw is None:
            continue
        raw_str = str(raw).strip()
        if not raw_str or raw_str == 'nan' or raw_str == '-' or raw_str == '0':
            continue
        val = parse_currency(raw)
        # Check if the raw value looks numeric but might have precision issues
        if val != 0 and '.' in raw_str:
            # Check for more than 2 decimal places
            parts = raw_str.replace('$','').replace(',','').split('.')
            if len(parts) == 2 and len(parts[1]) > 2:
                print(f"  Row {i}, {col}: raw='{raw_str}' -> {val} (>2 decimals)")
