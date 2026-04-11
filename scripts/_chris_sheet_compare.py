"""
Fetch Chris's sheet CSV and compare specific rows that MT5 push updated.
Check what values were in those cells BEFORE the push to understand the delta.
"""
import sys, csv, io, requests
sys.path.insert(0, '.')
from utils.data_processor import parse_currency

SHEET_KEY = '1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs'
CSV_URL = f'https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv&gid=0'

print("Fetching sheet CSV...")
resp = requests.get(CSV_URL, timeout=30)
resp.raise_for_status()

reader = csv.DictReader(io.StringIO(resp.text))
rows = list(reader)
print(f"Got {len(rows)} rows from sheet")

# The MT5 push updated these eval indices (0-based in the DB evals list)
# Log shows eval_idx values. Row numbers in the logs are +2 offset (header + 0-index)
# Let's check the specific rows

# From server.log, these sessions were matched:
# eval_idx -> column -> value pushed
updates = [
    (473, 'Hedge Result 1.1', 724.00, 'MFFU-80255'),
    (474, 'Hedge Result 1.1', 703.04, 'MFFU-80256'),
    (475, 'Hedge Result 1.1', 726.72, 'MFFU-80257'),
    (476, 'Hedge Result 1.1', 736.00, 'MFFU-80258'),
    (487, 'Hedge Result 1', -93.24, 'TDFY-93025'),
    (488, 'Hedge Result 1', -97.56, 'TDFY-83573'),
    (447, 'Hedge Result 2.1', 1089.90, 'TDF-59522'),
    (449, 'Hedge Day 8', -156.28, 'TDF-33548'),
    (484, 'Hedge Result 2', -150.25, 'FNFT-86721'),
    (486, 'Hedge Result 1', -101.38, 'FNFT-35212'),
    (485, 'Hedge Result 1', -95.57, 'FNFT-71311'),
    (445, 'Hedge Day 8', -190.11, 'FNFT-76770'),
    (446, 'Hedge Day 7', -178.85, 'FNFT-46494'),
    (338, 'Hedge Result 1', -194.76, 'V2-3458'),
    (217, 'Hedge Result 1', -195.82, 'V2-1128'),
    (491, 'Hedge Result 1', -197.48, 'V2-6849'),
]

print("\n" + "=" * 110)
print("SHEET VALUES (BEFORE MT5 PUSH) vs MT5 PUSHED VALUES")
print("=" * 110)

total_sheet_before = 0.0
total_mt5_pushed = 0.0

for idx, col, pushed_val, acct in updates:
    if idx < len(rows):
        sheet_row = rows[idx]
        sheet_val_raw = sheet_row.get(col, '')
        sheet_val = parse_currency(sheet_val_raw)
        diff = pushed_val - sheet_val
        changed = "CHANGED" if abs(diff) > 0.01 else "same"
        
        firm = sheet_row.get('Prop Firm', '?')
        acct_num = sheet_row.get('Account #', '?')[-10:] if sheet_row.get('Account #') else '?'
        
        total_sheet_before += sheet_val
        total_mt5_pushed += pushed_val
        
        print(f"  [{idx:3d}] {firm:20s} | {col:20s} | Sheet: ${sheet_val:>10.2f} ({str(sheet_val_raw):>12s}) | MT5: ${pushed_val:>10.2f} | Delta: ${diff:>+10.2f} | {changed}")
    else:
        print(f"  [{idx:3d}] OUT OF RANGE (sheet has {len(rows)} rows)")

print(f"\n  Total sheet before: ${total_sheet_before:,.2f}")
print(f"  Total MT5 pushed:  ${total_mt5_pushed:,.2f}")
print(f"  Net delta from MT5 push: ${total_mt5_pushed - total_sheet_before:,.2f}")

# Also show rows that have "MON" or "SEE NOTE" values (incomplete data)
print("\n" + "=" * 110)
print("ROWS WITH 'MON' or 'SEE NOTE' VALUES (incomplete hedge data)")
print("=" * 110)
HEDGE_COLS = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5',
              'Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1','Hedge Result 5.1',
              'Hedge Result 6','Hedge Result 7']

mon_count = 0
for i, row in enumerate(rows):
    for col in HEDGE_COLS:
        val = str(row.get(col, '')).strip().upper()
        if val in ('MON', 'SEE NOTE', 'TUE', 'WED', 'THU', 'FRI'):
            firm = row.get('Prop Firm', '?')
            acct = row.get('Account #', '?')
            print(f"  [{i:3d}] {firm:20s} | {col:20s} = '{row.get(col, '')}' | Acct={acct}")
            mon_count += 1

print(f"\n  Found {mon_count} incomplete hedge cells")
