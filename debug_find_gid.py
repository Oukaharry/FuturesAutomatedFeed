"""
Find the correct Evaluations tab GID by:
1. Trying Sheets API feed (may be public)
2. Systematic probe of common GIDs
3. Checking raw CSV rows 0-5 of gid=0 to understand the actual header structure
"""
import sys, requests, re, io
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

# ── 1. Try Sheets API feed ────────────────────────────────────────────────────
print("=== Sheets Feed API ===")
feeds = [
    f'https://spreadsheets.google.com/feeds/worksheets/{KEY}/public/basic?alt=json',
    f'https://docs.google.com/spreadsheets/d/{KEY}/feed/worksheets/public/basic?alt=json',
]
for url in feeds:
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        print(f"Status {r.status_code}: {url}")
        if r.ok and 'entry' in r.text:
            import json
            data = json.loads(r.text)
            entries = data.get('feed', {}).get('entry', [])
            for e in entries:
                title = e.get('title', {}).get('$t', '')
                gid = None
                for link in e.get('link', []):
                    if '/gid=' in link.get('href', ''):
                        gid = link['href'].split('/gid=')[-1].split('/')[0]
                print(f"  Tab: {title!r:30s}  gid={gid}")
            break
        elif r.ok:
            print(f"  Unexpected response: {r.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

# ── 2. Look at raw rows 0-6 of gid=0 ─────────────────────────────────────────
print("\n=== Raw rows 0-5 of gid=0 ===")
url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid=0'
r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
if r.ok:
    df = pd.read_csv(io.StringIO(r.text), header=None, nrows=6)
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.width', 200)
    for i, row in df.iterrows():
        print(f"\nRow {i}:")
        for j, val in enumerate(row):
            if str(val).strip() and str(val).strip() != 'nan':
                print(f"  col[{j:>3}] = {val!r}")

# ── 3. Systematic probe of plausible GIDs ─────────────────────────────────────
print("\n=== Systematic GID probe ===")
# Try GIDs that are common/generated (many sheets auto-assign around 0-5 for early tabs,
# or random large numbers). We probe 0-10 and some larger ones.
probe_gids = list(range(0, 12)) + [100, 200, 839895136]
print(f"{'GID':>12}  {'status':>6}  {'rows':>5}  {'col[0]':>8}  first real-value cols")
print("-"*80)
for gid in probe_gids:
    url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={gid}'
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            print(f"{gid:>12}  {r.status_code:>6}")
            continue
        lines = r.text.strip().split('\n')
        df = pd.read_csv(io.StringIO(r.text), header=None, nrows=2)
        row0_vals = [str(v).strip() for v in df.iloc[0] if str(v).strip() and str(v) != 'nan']
        print(f"{gid:>12}  {r.status_code:>6}  {len(lines):>5}  {row0_vals[:5]}")
    except Exception as e:
        print(f"{gid:>12}  ERROR  {e}")
