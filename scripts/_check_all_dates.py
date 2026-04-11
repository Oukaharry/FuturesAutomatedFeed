"""Find all unique date formats across multiple clients."""
from dashboard.database import get_client_data
from config.hierarchy import get_all_clients

all_clients = get_all_clients()
date_fields = ['Date Purchased', 'Date Started', 'Date Ended', 
               'Date Started.1', 'Date Ended.1',
               'Date 1', 'Date 2', 'Date 3', 'Date 4']

# Collect unique date patterns
samples = set()
for client_name in all_clients:
    data = get_client_data(client_name)
    if not data:
        continue
    for ev in data.get('evaluations', []):
        if ev.get('_deleted'):
            continue
        for f in date_fields:
            v = str(ev.get(f, '') or '').strip()
            if v:
                samples.add(v)

# Show unique patterns sorted
print(f"Total unique date strings: {len(samples)}")
# Group by pattern (number of slashes, dashes, length)
from collections import defaultdict
patterns = defaultdict(list)
for s in sorted(samples):
    parts = s.replace('-', '/').split('/')
    pattern = '/'.join(['N'] * len(parts)) + f" (lens={'|'.join(str(len(p)) for p in parts)})"
    patterns[pattern].append(s)

for pat, vals in sorted(patterns.items()):
    print(f"\n  Pattern: {pat}  ({len(vals)} values)")
    for v in sorted(vals)[:10]:
        print(f"    {v}")
    if len(vals) > 10:
        print(f"    ... and {len(vals)-10} more")
