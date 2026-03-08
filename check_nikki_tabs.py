"""Try to read the Stats tab from Nikki's sheet and show what it says."""
import sys, json, re, requests
sys.path.insert(0, '.')

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

# -- Try to discover stats GID from edit page --------------------------------
print("Scanning sheet HTML for tab GIDs...")
r = requests.get(f'https://docs.google.com/spreadsheets/d/{KEY}/edit', timeout=15,
                 headers={'User-Agent': 'Mozilla/5.0'})
print(f"HTML status: {r.status_code}  size: {len(r.text)}")

tabs = {}
# Pattern used by Google Sheets in its bootstrap JSON
for m in re.finditer(r'"(\d{6,12})"[^"]{0,60}"([^"]{2,40})"', r.text):
    gid, name = m.group(1), m.group(2)
    if any(c.isalpha() for c in name):
        tabs[name] = gid

if tabs:
    print("Tabs found:")
    for name, gid in tabs.items():
        print(f"  {name!r:40s} gid={gid}")
else:
    print("No tabs found in HTML parse — trying brute-force GID CSV scan")

# -- Try known/likely GIDs for Stats tab ------------------------------------
CANDIDATE_GIDS = list(set(tabs.values())) or ['0','1','2','1234567','520289647']

for gid in CANDIDATE_GIDS[:10]:
    csv_url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={gid}'
    r2 = requests.get(csv_url, timeout=10, allow_redirects=True,
                      headers={'User-Agent': 'Mozilla/5.0'})
    if r2.ok and r2.text.strip():
        first_line = r2.text.strip().splitlines()[0][:80]
        print(f"  gid={gid}  ✓  first line: {first_line}")
    else:
        print(f"  gid={gid}  status={r2.status_code}")
