"""Fetch all tab names and the Stats tab data from Nikki's sheet."""
import sys, json, re, requests
sys.path.insert(0, '.')

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

# ── List all tabs ─────────────────────────────────────────────────────────────
url = f'https://spreadsheets.google.com/feeds/worksheets/{KEY}/public/basic?alt=json'
r = requests.get(url, timeout=15)
print('Metadata status:', r.status_code)
tabs = {}
if r.ok:
    for entry in r.json().get('feed', {}).get('entry', []):
        title = entry.get('title', {}).get('$t', '')
        href  = next((l['href'] for l in entry.get('link', []) if 'gid' in l.get('href', '')), '')
        m = re.search(r'gid=(\d+)', href)
        gid = m.group(1) if m else '?'
        tabs[title] = gid
        print(f'  {title!r:30s}  gid={gid}')

# ── Pull Stats tab ────────────────────────────────────────────────────────────
stats_gid = next((g for t, g in tabs.items() if 'stat' in t.lower()), None)
if not stats_gid:
    print('\nNo Stats tab found — trying gid=1')
    stats_gid = '1'

print(f'\nFetching Stats tab (gid={stats_gid})…')
csv_url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={stats_gid}'
r2 = requests.get(csv_url, timeout=15)
print('CSV status:', r2.status_code)
if r2.ok:
    lines = r2.text.strip().splitlines()
    for line in lines[:40]:
        print(' ', line)
