"""Print all columns and sums from Nikki's evaluations to verify column mapping."""
import sys
sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

evals = fetch_evaluations('https://docs.google.com/spreadsheets/d/1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M/edit')[0]
if evals:
    keys = list(evals[0].keys())
    print(f'Total columns: {len(keys)}\n')
    print('All columns with non-zero sums:')
    for k in keys:
        total = sum(parse_currency(ev.get(k)) for ev in evals)
        if abs(total) > 0.01:
            print(f'  {k!r:45s} sum={total:>14,.2f}')
    print('\nAll column names:')
    for i, k in enumerate(keys):
        print(f'  [{i:3d}] {k!r}')

