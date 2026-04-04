"""Check what partials from the dashboard screenshot our session_accounts can resolve."""
import json

with open('_chris_ream_extracted.json') as f:
    data = json.load(f)

# Build session lookup
session_lookup = {}
for sa in data['session_accounts']:
    session_lookup[sa] = sa
    if '-' in sa:
        partial = sa.rsplit('-', 1)[-1]
        session_lookup[partial] = sa

# Test the partial values from the screenshot
test_partials = ['45809', 'M2247', '47894', '74587', 'M9661', '0494', '9152', '3083', '57520']
print("=== Can session_accounts resolve screenshot partials? ===")
for p in test_partials:
    full = session_lookup.get(p)
    print(f"  {p:>8s} -> {full or 'NOT FOUND'}")

# Also check all account_maps entries for unresolved
print(f"\n=== All account_map partials that DON'T resolve ===")
for row_str, entries in data['account_maps'].items():
    for entry in entries:
        acct = entry['account']
        full = session_lookup.get(acct)
        if not full or '-' not in full:
            print(f"  Row {row_str}: account=[{acct}]  phase={entry['phase']}")

# Show how many unique session accounts we have by prefix
from collections import Counter
prefixes = Counter()
for sa in data['session_accounts']:
    if '-' in sa:
        prefix = sa.rsplit('-', 1)[0]
        prefixes[prefix] += 1
    else:
        prefixes['NO-PREFIX'] += 1
print(f"\n=== Session account prefix breakdown ===")
for prefix, count in prefixes.most_common():
    print(f"  {prefix}: {count}")
