"""Debug account number resolution in the extracted CSV."""
import csv, json

with open('_chris_ream_full.csv', encoding='utf-8') as f:
    rows = [r for r in csv.DictReader(f) if r.get('Row #','').strip() and '---' not in r.get('Row #','')]

# Check rows 168-175 (from screenshot)
print('=== Rows 168-175 from CSV ===')
for r in rows:
    idx = r.get('Row #','')
    if idx.isdigit() and 168 <= int(idx) <= 175:
        print(f"  Row {idx}: Acct=[{r.get('Account #','')}]  Acct.1=[{r.get('Account #.1','')}]  Firm=[{r.get('Prop Firm','')}]")

# Count partial vs full account numbers
full_ch = partial_ch = empty_ch = 0
full_fa = partial_fa = empty_fa = 0
for r in rows:
    a = r.get('Account #','').strip()
    if not a: empty_ch += 1
    elif '-' in a: full_ch += 1
    else: partial_ch += 1
    a1 = r.get('Account #.1','').strip()
    if not a1: empty_fa += 1
    elif '-' in a1: full_fa += 1
    else: partial_fa += 1

print(f"\n=== Account # format ===")
print(f"  Full (e.g. FNFT-45809): {full_ch}")
print(f"  Partial (e.g. 45809):   {partial_ch}")
print(f"  Empty:                   {empty_ch}")
print(f"\n=== Account #.1 format ===")
print(f"  Full (e.g. MFFU-66028): {full_fa}")
print(f"  Partial (e.g. 66028):   {partial_fa}")
print(f"  Empty:                   {empty_fa}")

# Show partial examples
print(f"\n=== Sample PARTIAL Account # ===")
cnt = 0
for r in rows:
    a = r.get('Account #','').strip()
    if a and '-' not in a:
        print(f"  Row {r['Row #']:>3}: [{a:15s}]  Firm=[{r.get('Prop Firm','')}]")
        cnt += 1
        if cnt >= 20: break

print(f"\n=== Sample PARTIAL Account #.1 ===")
cnt = 0
for r in rows:
    a = r.get('Account #.1','').strip()
    if a and '-' not in a:
        print(f"  Row {r['Row #']:>3}: [{a:15s}]  Firm=[{r.get('Prop Firm','')}]")
        cnt += 1
        if cnt >= 20: break

# Check the JSON account_maps — are partials matching session_accounts?
with open('_chris_ream_extracted.json') as f:
    data = json.load(f)

session_accounts = set(data['session_accounts'])
session_lookup = {}
for sa in session_accounts:
    session_lookup[sa] = sa
    if '-' in sa:
        partial = sa.rsplit('-', 1)[-1]
        session_lookup[partial] = sa

account_maps = data['account_maps']
resolved = 0
unresolved = 0
unresolved_samples = []
for row_str, entries in account_maps.items():
    for entry in entries:
        acct = entry['account']
        full = session_lookup.get(acct)
        if full and '-' in full:
            resolved += 1
        else:
            unresolved += 1
            if len(unresolved_samples) < 20:
                unresolved_samples.append((row_str, acct, entry['phase']))

print(f"\n=== Account map resolution ===")
print(f"  Resolved to full name: {resolved}")
print(f"  UNRESOLVED (stays partial): {unresolved}")
if unresolved_samples:
    print(f"\n  Unresolved samples:")
    for row, acct, phase in unresolved_samples:
        print(f"    Row {row}: account=[{acct}] phase={phase}")
