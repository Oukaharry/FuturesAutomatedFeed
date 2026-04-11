"""Better matching: use ALL non-account fields to uniquely match 649 DB rows 
to the 1455 original CSV rows and restore original account numbers."""
import csv, json, sqlite3
from collections import Counter, defaultdict

ORIG_CSV = r'c:\Users\harry\Downloads\Chris_evaluations.csv'
FIXED_CSV = r'c:\Users\harry\Downloads\Chris_evaluations_fixed.csv'
DB_PATH = 'dashboard/dashboard.db'

# Read original CSV
with open(ORIG_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    orig_fields = reader.fieldnames
    orig_rows = list(reader)

# Read current DB
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
db_evals = json.loads(cur.fetchone()[0])

print(f'Original CSV: {len(orig_rows)} rows')
print(f'DB: {len(db_evals)} evals')

# Strategy: The original 1455 rows each has unique accounts. 
# The DB 649 rows are the deduped set.
# We need to find which of the 1455 rows correspond to the 649 DB rows.
# 
# Approach: Use many fields (excluding Account # and Account #.1) as matching key.
# Fields that should be stable: Prop Firm, Date Purchased, Account Size, Phase, 
# Status, Eval #, Net Profit, etc.

SKIP_FIELDS = {'Account #', 'Account #.1'}

# Build a rich key from many fields
def make_rich_key(row, fields_to_use):
    """Create a tuple of all non-account field values."""
    parts = []
    for f in fields_to_use:
        if f in SKIP_FIELDS:
            continue
        val = (row.get(f) or '').strip()
        parts.append(val)
    return tuple(parts)

# Get common fields between CSV and DB
# DB evals are dicts with potentially different keys
# Let's check what keys DB evals have
all_db_keys = set()
for ev in db_evals:
    all_db_keys.update(ev.keys())

common_fields = [f for f in orig_fields if f in all_db_keys and f not in SKIP_FIELDS]
print(f'Common non-account fields for matching: {len(common_fields)}')

# Build lookup from original CSV
orig_by_key = defaultdict(list)
for i, row in enumerate(orig_rows):
    key = make_rich_key(row, common_fields)
    orig_by_key[key].append(i)

# Match DB rows to original
matched = []
unmatched_db = []
multi_match = 0

for db_idx, ev in enumerate(db_evals):
    key = make_rich_key(ev, common_fields)
    candidates = orig_by_key.get(key, [])
    
    if len(candidates) == 1:
        matched.append((db_idx, candidates[0]))
    elif len(candidates) > 1:
        # Multiple matches in original - take first unused
        matched.append((db_idx, candidates[0]))
        multi_match += 1
    else:
        unmatched_db.append(db_idx)

print(f'Uniquely matched: {len(matched) - multi_match}')
print(f'Multi-matched (took first): {multi_match}')
print(f'Unmatched DB rows: {len(unmatched_db)}')

# Show unmatched samples
if unmatched_db:
    print(f'\n=== Unmatched DB row samples ===')
    for idx in unmatched_db[:10]:
        ev = db_evals[idx]
        firm = (ev.get('Prop Firm') or '').strip()
        date = (ev.get('Date Purchased') or '').strip()
        size = (ev.get('Account Size') or '').strip()
        phase = (ev.get('Phase') or '').strip()
        status = (ev.get('Status') or '').strip()
        print(f'  DB row {idx}: {firm} {date} {size} Phase={phase!r} Status={status!r}')

# Check multi-matches
print(f'\n=== Multi-match breakdown ===')
multi_keys = []
for db_idx, ev in enumerate(db_evals):
    key = make_rich_key(ev, common_fields)
    candidates = orig_by_key.get(key, [])
    if len(candidates) > 1:
        multi_keys.append((db_idx, len(candidates)))

# How many unique multi-match keys?
multi_key_counts = Counter(c for _, c in multi_keys)
for count, freq in sorted(multi_key_counts.items()):
    print(f'  {count} original matches per DB row: {freq} DB rows')
