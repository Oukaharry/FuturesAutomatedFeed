"""Debug farming in calculate_statistics"""
import sys
sys.path.insert(0, '..')
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/edit'

print("Fetching data...")
evals = fetch_evaluations(SHEET_URL)
print(f"Records: {len(evals)}")

# Find a completed record
completed = [e for e in evals if str(e.get('Status', '')).strip() == 'Completed']
print(f"Completed accounts: {len(completed)}")

# Check hedge day columns in first completed record
if completed:
    ev = completed[0]
    print(f"\nFirst completed record keys containing 'Hedge Day':")
    for k in ev.keys():
        if 'hedge day' in k.lower():
            print(f"  '{k}': {ev[k]}")

# Calculate farming total for all completed accounts
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]
farming_total = 0
for ev in completed:
    for col in HEDGE_DAY_COLS:
        val = parse_currency(ev.get(col))
        farming_total += val

print(f"\nFarming total using 'Hedge Day 1'..'Hedge Day 34': ${farming_total:.2f}")
print(f"Expected: $582.72")

# Check if there are duplicate Hedge Day columns
all_keys = set()
for ev in evals[:1]:
    for k in ev.keys():
        if 'hedge' in k.lower():
            all_keys.add(k)
print(f"\nAll hedge-related columns in data:")
for k in sorted(all_keys):
    print(f"  {k}")
