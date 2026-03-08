"""
Find all GIDs in Nikki's sheet, probe each tab header,
then compare hedge sums between tabs to find correct Evaluations tab.
"""
import sys, requests, re, io
sys.path.insert(0, '.')
import pandas as pd

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

P1_COLS = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_COLS = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
           'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']

def parse_currency(v):
    if v is None: return 0.0
    try: return float(str(v).replace(',','').replace('$','').strip())
    except: return 0.0

def get_csv(gid, header_row=0):
    url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={gid}'
    r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    if not r.ok:
        return None, r.status_code
    try:
        df = pd.read_csv(io.StringIO(r.text), header=header_row, dtype=str)
        return df, 200
    except Exception as e:
        return None, str(e)

# ── 1. Fetch HTML for GID list ────────────────────────────────────────────────
print("Fetching sheet HTML for tab GIDs...")
try:
    r = requests.get(f'https://docs.google.com/spreadsheets/d/{KEY}/edit', timeout=15,
                     headers={'User-Agent': 'Mozilla/5.0'})
    gid_hits = list(dict.fromkeys(re.findall(r'gid=(\d+)', r.text)))
    print(f"GIDs in HTML ({len(gid_hits)} found): {gid_hits[:25]}")
except Exception as e:
    print(f"HTML fetch failed: {e}")
    gid_hits = []

# ── 2. Probe each GID ────────────────────────────────────────────────────────
candidate_gids = list(dict.fromkeys(['0', '839895136'] + gid_hits[:20]))
print(f"\nProbing {len(candidate_gids)} GIDs:")
print(f"{'GID':>15}  {'rows':>5}  First 4 columns")
print("-"*80)
for gid in candidate_gids:
    df, status = get_csv(gid)
    if df is None:
        print(f"{gid:>15}  ERROR  {status}")
        continue
    cols = list(df.columns)[:4]
    print(f"{gid:>15}  {len(df):>5}  {cols}")

# ── 3. Sum hedge cols on gid=0 ───────────────────────────────────────────────
print("\nHedge sums from gid=0 via fetch_evaluations():")
from utils.data_processor import fetch_evaluations
evals, _ = fetch_evaluations(f'https://docs.google.com/spreadsheets/d/{KEY}/edit')
all_p1h = sum(parse_currency(ev.get(c)) for ev in evals for c in P1_COLS)
all_fdh = sum(parse_currency(ev.get(c)) for ev in evals for c in FD_COLS)
print(f"  rows = {len(evals)}")
print(f"  SUM(J:N) = {all_p1h:>12,.2f}")
print(f"  SUM(U:AA) = {all_fdh:>12,.2f}")
print(f"  TOTAL     = {all_p1h+all_fdh:>12,.2f}   (sheet expects -30,959.91)")
print(f"  DIFF      = {(all_p1h+all_fdh) - (-30959.91):>+12,.2f}")

# ── 4. Show raw first row of gid=0 to see column layout ──────────────────────
print("\nColumn names from gid=0 (first header row):")
df0, _ = get_csv('0', header_row=0)
if df0 is not None:
    for i, col in enumerate(df0.columns):
        print(f"  [{i:>3}] {col}")
