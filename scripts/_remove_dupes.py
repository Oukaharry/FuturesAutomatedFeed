"""Remove duplicate row 641, merge newer data into row 527.
Also check for and remove any other duplicates found."""
import json, sqlite3, csv
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'
CSV_PATH = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])

print(f'Before: {len(evals)} evals')

# Merge row 641 newer data into row 527
ev527 = evals[527]
ev641 = evals[641]

# Row 641 has better values for these fields:
# Date Ended: '03/17/2026' vs '03/17/20' (truncated)
# Status P1: 'In Progress' vs 'Fail' - 641 is more current
# Hedge Result 1: '164.88' vs '$211.60' - keep 527's as it has the $ format
# Hedge Net: 527 has '104.6', 641 is empty - keep 527's

print(f'\nMerging into row 527:')
print(f'  Date Ended: {ev527.get("Date Ended")!r} -> {ev641.get("Date Ended")!r}')
print(f'  Status P1: {ev527.get("Status P1")!r} -> {ev641.get("Status P1")!r}')

ev527['Date Ended'] = ev641.get('Date Ended', ev527.get('Date Ended'))
ev527['Status P1'] = ev641.get('Status P1', ev527.get('Status P1'))
evals[527] = ev527

# Remove row 641
evals.pop(641)
print(f'\nRemoved duplicate row 641')

# Check for other duplicates and remove them too
# Found these duplicate pairs:
# ('My Funded Futures', '', 'MFFU-71140', 'MFFU-80295') x3
# ('Topstep', '01/20/2026', ...) x2
# ('Topstep', '01/26/2026', ...) x2
# Plus several with empty dates

def make_acct_key(ev):
    return (
        (ev.get('Prop Firm') or '').strip(),
        (ev.get('Date Purchased') or '').strip(),
        (ev.get('Account #') or '').strip(),
        (ev.get('Account #.1') or '').strip(),
    )

# Find all duplicate groups
key_to_indices = {}
for i, ev in enumerate(evals):
    k = make_acct_key(ev)
    if k[2]:  # only consider rows with Account #
        key_to_indices.setdefault(k, []).append(i)

dupes_to_remove = []
for k, indices in key_to_indices.items():
    if len(indices) > 1:
        # Keep the first, remove the rest (merge newer data first)
        keep = indices[0]
        for remove_idx in indices[1:]:
            # Merge: if the later row has non-empty values where the kept row is empty, use them
            for field in evals[remove_idx]:
                new_val = (str(evals[remove_idx].get(field, '')) or '').strip()
                old_val = (str(evals[keep].get(field, '')) or '').strip()
                if new_val and not old_val:
                    evals[keep][field] = evals[remove_idx][field]
            dupes_to_remove.append(remove_idx)
        print(f'  Dupe: {k[0]:<22} Date={k[1]:12} A={k[2]!r} - keeping row {keep}, removing {indices[1:]}')

# Remove in reverse order to keep indices stable
dupes_to_remove.sort(reverse=True)
for idx in dupes_to_remove:
    evals.pop(idx)

print(f'\nRemoved {len(dupes_to_remove)} additional duplicates')
print(f'After: {len(evals)} evals')

# Re-number Row #
for i, ev in enumerate(evals):
    ev['Row #'] = str(i)

# Save to DB
cur.execute("UPDATE clients_data SET evaluations=? WHERE client_id='Chris'", (json.dumps(evals),))
db.commit()
db.close()

# Save to CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames

# Build CSV rows from DB evals
csv_rows = []
for ev in evals:
    row = {}
    for f in fieldnames:
        row[f] = ev.get(f, '')
    csv_rows.append(row)

with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)

# Verify no more duplicates
key_counts = Counter()
for ev in evals:
    k = make_acct_key(ev)
    if k[2]:
        key_counts[k] += 1
remaining_dupes = {k: c for k, c in key_counts.items() if c > 1}
print(f'\nRemaining duplicates: {len(remaining_dupes)}')
if remaining_dupes:
    for k, c in remaining_dupes.items():
        print(f'  {c}x: {k}')

print(f'\nDB and CSV updated. Final: {len(evals)} evals')
