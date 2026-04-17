"""Final comprehensive audit of Chris's data."""
import json, sqlite3
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

print(f'Total evals: {len(evals)}')

# ---- Field completeness ----
all_fields = set()
for ev in evals:
    all_fields.update(ev.keys())

print(f'\n=== FIELD COMPLETENESS (Populated Fields) ===')
field_data = []
for f in sorted(all_fields):
    count = sum(1 for ev in evals if str(ev.get(f, '') or '').strip())
    if count > 0:
        pct = count / len(evals) * 100
        field_data.append((f, count, pct))

field_data.sort(key=lambda x: -x[1])
for f, c, p in field_data:
    bar = '█' * int(p/5) + '░' * (20 - int(p/5))
    print(f'  {f:<30} {c:>4}/{len(evals)} ({p:5.1f}%) {bar}')

# ---- Sparse rows (few fields populated) ----
row_densities = []
for i, ev in enumerate(evals):
    populated = sum(1 for k, v in ev.items() if str(v or '').strip() and k != 'Row #')
    row_densities.append((i, populated, ev.get('Prop Firm',''), ev.get('Account #','')))

avg_density = sum(d[1] for d in row_densities) / len(row_densities)
print(f'\n=== ROW DENSITY ===')
print(f'Average fields per row: {avg_density:.1f}')

density_dist = Counter(d[1] for d in row_densities)
print(f'\nDensity distribution:')
for n in sorted(density_dist.keys()):
    print(f'  {n:>3} fields: {density_dist[n]:>3} rows')

row_densities.sort(key=lambda r: r[1])
print(f'\n=== SPARSEST ROWS ===')
for row, cnt, firm, acct in row_densities[:20]:
    print(f'  Row {row:>3}: {cnt:>2} fields | {str(firm)[:22]:<22} | Acct={str(acct)!r}')

# ---- Account coverage ----
has_acct = sum(1 for ev in evals if str(ev.get('Account #','') or '').strip())
has_acct1 = sum(1 for ev in evals if str(ev.get('Account #.1','') or '').strip())
has_both = sum(1 for ev in evals if str(ev.get('Account #','') or '').strip() and str(ev.get('Account #.1','') or '').strip())
has_neither = sum(1 for ev in evals if not str(ev.get('Account #','') or '').strip() and not str(ev.get('Account #.1','') or '').strip())

print(f'\n=== ACCOUNT COVERAGE ===')
print(f'  Account #:     {has_acct}/{len(evals)} ({has_acct/len(evals)*100:.1f}%)')
print(f'  Account #.1:   {has_acct1}/{len(evals)} ({has_acct1/len(evals)*100:.1f}%)')
print(f'  Both:          {has_both}/{len(evals)} ({has_both/len(evals)*100:.1f}%)')
print(f'  Neither:       {has_neither}/{len(evals)} ({has_neither/len(evals)*100:.1f}%)')

# ---- Firm breakdown ----
firm_counts = Counter(str(ev.get('Prop Firm','') or '').strip() for ev in evals)
print(f'\n=== FIRM BREAKDOWN ===')
for firm, count in firm_counts.most_common():
    print(f'  {firm:<25} {count:>4}')

# ---- Status breakdown ----
status_counts = Counter(str(ev.get('Status P1','') or '').strip() for ev in evals)
print(f'\n=== STATUS P1 BREAKDOWN ===')
for s, c in status_counts.most_common():
    print(f'  {s or "(empty)":<20} {c:>4}')

# ---- Date coverage ----
has_date_purchased = sum(1 for ev in evals if str(ev.get('Date Purchased','') or '').strip())
has_date_started = sum(1 for ev in evals if str(ev.get('Date Started','') or '').strip())
has_date_ended = sum(1 for ev in evals if str(ev.get('Date Ended','') or '').strip())
has_fee = sum(1 for ev in evals if str(ev.get('Fee','') or '').strip())
has_size = sum(1 for ev in evals if str(ev.get('Account Size','') or '').strip())

print(f'\n=== KEY FIELD COVERAGE ===')
print(f'  Date Purchased:  {has_date_purchased}/{len(evals)} ({has_date_purchased/len(evals)*100:.1f}%)')
print(f'  Account Size:    {has_size}/{len(evals)} ({has_size/len(evals)*100:.1f}%)')
print(f'  Fee:             {has_fee}/{len(evals)} ({has_fee/len(evals)*100:.1f}%)')
print(f'  Date Started:    {has_date_started}/{len(evals)} ({has_date_started/len(evals)*100:.1f}%)')
print(f'  Date Ended:      {has_date_ended}/{len(evals)} ({has_date_ended/len(evals)*100:.1f}%)')

# Rows missing Date Purchased (which ones?)
missing_date = [(i, str(ev.get('Prop Firm','')), str(ev.get('Account #','')), str(ev.get('Status P1',''))) 
                for i, ev in enumerate(evals) if not str(ev.get('Date Purchased','') or '').strip()]
print(f'\n=== ROWS MISSING DATE PURCHASED ({len(missing_date)}) ===')
for row, firm, acct, status in missing_date:
    print(f'  Row {row:>3}: {firm:<22} Acct={acct!r:25} Status={status}')

# ---- Duplicate check ----
seen = {}
dupes = []
for i, ev in enumerate(evals):
    a = str(ev.get('Account #','') or '').strip()
    a1 = str(ev.get('Account #.1','') or '').strip()
    f = str(ev.get('Prop Firm','') or '').strip()
    key = (f, a, a1)
    if a and key in seen:
        dupes.append((i, seen[key], key))
    elif a:
        seen[key] = i

print(f'\n=== DUPLICATE CHECK ===')
print(f'Duplicates found: {len(dupes)}')
for i, prev, key in dupes:
    print(f'  Row {i} = Row {prev}: {key}')

print(f'\n=== SUMMARY ===')
print(f'Total evaluations: {len(evals)}')
print(f'Duplicates: {len(dupes)}')
print(f'Account # coverage: {has_acct/len(evals)*100:.1f}%')
print(f'Date Purchased coverage: {has_date_purchased/len(evals)*100:.1f}%')
print(f'Hedge Result 1 coverage: {sum(1 for ev in evals if str(ev.get("Hedge Result 1","") or "").strip())/len(evals)*100:.1f}%')
