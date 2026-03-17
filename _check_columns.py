import requests, io, pandas as pd, sys

url = 'https://docs.google.com/spreadsheets/d/1JK1lCkfj8GRQEKD2AOILms8LZom3I5zQ-_UrQU9xw8o/export?format=csv'
r = requests.get(url, timeout=30)
df = pd.read_csv(io.StringIO(r.text), header=1)

# Show all columns with "account" in name
print("=== Account-related columns ===")
for i, c in enumerate(df.columns):
    if 'account' in str(c).lower() or 'unnamed: 15' in str(c).lower():
        print(f'  Col {i}: [{c}]')

has_acc1 = 'Account #.1' in df.columns
print(f'\nHas Account #.1: {has_acc1}')

if has_acc1:
    vals = df['Account #.1'].dropna()
    print(f'Non-empty Account #.1: {len(vals)}')
    for v in vals.head(10):
        print(f'  {v}')

# Also check: what columns exist that are NOT in the allowed_columns list
allowed_columns = [
    'Prop Firm', 'Account Size', 'Date Purchased', 'Fee',
    'Date Started', 'Date Ended', 'Status P1', 'Account #',
    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
    'Account #.1', 'Activation Fee', 'Date Started.1', 'Date Ended.1', 'Status', 'Status Funded',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1',
    'Hedge Result 6', 'Hedge Result 7', 'Hedge Net.1',
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2', 'Payout 3', 'Date 3', 'Payout 4', 'Date 4',
    'Farming Net'
]
for i in range(1, 35):
    allowed_columns.append(f'Prop Day {i}')
    allowed_columns.append(f'Hedge Day {i}')

dropped = [c for c in df.columns if c not in allowed_columns and not c.startswith('Unnamed')]
print(f'\n=== Columns in sheet but NOT in allowed_columns ({len(dropped)}) ===')
for c in dropped:
    print(f'  [{c}]')

# Check if any Account # values look wrong (contain letters that might cause display issues)
acc_col = df['Account #'].dropna()
print(f'\n=== Sample Account # values (first 10) ===')
for v in acc_col.head(10):
    print(f'  [{v}]')
