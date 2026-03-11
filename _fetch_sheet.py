import urllib.request, csv, io, json

sheet_id = '1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs'
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

print("Fetching sheet...")
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=30)
data = resp.read().decode('utf-8-sig')

reader = csv.DictReader(io.StringIO(data))
rows = list(reader)
print(f"Total rows: {len(rows)}")

# Print column names to understand structure
if rows:
    cols = list(rows[0].keys())
    hedge_cols = [c for c in cols if 'hedge' in c.lower() or 'Hedge' in c]
    print(f"\nAll columns ({len(cols)}):")
    for c in cols:
        print(f"  {c}")

# Find evaluations with FA accounts from the DB comparison
target_accounts = [
    '2641', '6337',     # eval 392 - V2-2641/6337  
    '76770',            # eval 445 - FNFT-76770
    '46494',            # eval 446 - FNFT-46494
    '57582',            # eval 448 - TDF-57582
    '33548',            # eval 449 - TDF-33548
    '80230',            # never matched
    '80229',            # eval 394 - skipped inactive
    '80233',            # eval 408 - skipped inactive
    '80237',            # eval 426 - skipped inactive
]

print("\n" + "="*70)
print("SEARCHING FOR FA ACCOUNTS IN SHEET:")
print("="*70)

for i, row in enumerate(rows):
    row_num = i + 2  # 1-indexed header + data
    acc = str(row.get('Account #', ''))
    acc1 = str(row.get('Account #.1', ''))
    for target in target_accounts:
        if target in acc or target in acc1:
            print(f"\n--- Row {row_num}: Found account containing '{target}' ---")
            print(f"  Account #: {acc}")
            print(f"  Account #.1: {acc1}")
            print(f"  Prop Firm: {row.get('Prop Firm', '')}")
            print(f"  Status P1: {row.get('Status P1', '')}")
            print(f"  Status: {row.get('Status', '')} / Funded: {row.get('Status Funded', '')}")
            for d in range(1, 35):
                val = row.get(f'Hedge Day {d}', '')
                if val and val.strip() and val.strip() != '$0.00' and val.strip() != '0':
                    print(f"  Hedge Day {d}: {val}")
            break
