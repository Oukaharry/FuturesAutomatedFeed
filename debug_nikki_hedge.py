"""
Check which GID each tab in Nikki's sheet is, then compare hedge sums
between gid=0 and other tabs to find the real Evaluations tab.
"""
import sys, requests, re, io
sys.path.insert(0, '.')
import pandas as pd
from utils.data_processor import parse_currency

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

P1_COLS = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_COLS = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
           'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']

def csv_rows(gid, header_row=0):
    url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={gid}'
    r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    if not r.ok:
        return None, r.status_code
    try:
        df = pd.read_csv(io.StringIO(r.text), header=header_row, dtype=str)
        return df, 200
    except Exception as e:
        return None, str(e)

# ── 1. Find all tab GIDs ──────────────────────────────────────────────────────
print("Scanning sheet HTML for tab GIDs...")
r = requests.get(f'https://docs.google.com/spreadsheets/d/{KEY}/edit', timeout=15,
                 headers={'User-Agent': 'Mozilla/5.0'})
gid_hits = list(dict.fromkeys(re.findall(r'gid=(\d+)', r.text)))
print(f"GIDs found in HTML: {gid_hits[:20]}")

# ── 2. For each GID fetch first row and row count ─────────────────────────────
print("\nProbing each GID:")
candidate_gids = list(dict.fromkeys(['0'] + gid_hits[:15]))
for gid in candidate_gids:
    df, status = csv_rows(gid)
    if df is None:
        print(f"  gid={gid:12s}  status={status}")
        continue
    first_cols = list(df.columns)[:6]
    print(f"  gid={gid:12s}  rows={len(df):4d}  first_cols={first_cols}")

# ── 3. Compute hedge sums from gid=0 vs known Evaluations data ────────────────
print("\nComputing hedge sums from gid=0...")
from utils.data_processor import fetch_evaluations
evals = fetch_evaluations(f'https://docs.google.com/spreadsheets/d/{KEY}/edit')[0]
all_p1h = sum(parse_currency(ev.get(c)) for ev in evals for c in P1_COLS)
all_fdh = sum(parse_currency(ev.get(c)) for ev in evals for c in FD_COLS)
print(f"  fetch_evaluations → {len(evals)} rows")
print(f"  SUM(J:N) = {all_p1h:,.2f}")
print(f"  SUM(U:AA) = {all_fdh:,.2f}")
print(f"  Total = {all_p1h + all_fdh:,.2f}  (sheet expects -30,959.91)")
print(f"  Diff  = {(all_p1h + all_fdh) - (-30959.91):+,.2f}")

# ── 4. What does gid=0 first line look like? ─────────────────────────────────
print("\nFirst 3 rows of gid=0 raw CSV:")
df0, _ = csv_rows('0', header_row=None)
if df0 is not None:
    print(df0.head(3).to_string())


SHEET_KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'

# ── 1. Find Nikki in DB ────────────────────────────────────────────────────────
all_clients = get_all_clients()
nikki_id = None
for cid, cdata in all_clients.items():
    name = str(cdata.get('identity', {}).get('client', '') or cdata.get('identity', {}).get('name', '')).lower()
    if 'nikki' in name or 'nik' in name:
        nikki_id = cid
        break

if not nikki_id:
    # Try email hint
    for cid, cdata in all_clients.items():
        email = str(cdata.get('identity', {}).get('email', '')).lower()
        sheet_url = str(cdata.get('sheet_url', '')).lower()
        if SHEET_KEY.lower() in sheet_url:
            nikki_id = cid
            break

if not nikki_id:
    print("❌ Could not find Nikki in DB by name or sheet URL.")
    print("Available clients:")
    for cid, cdata in all_clients.items():
        ident = cdata.get('identity', {})
        print(f"  {cid!r} → {ident}")
    sys.exit(1)

nikki_data = all_clients[nikki_id]
evals_db = nikki_data.get('evaluations', [])
stats_db  = nikki_data.get('statistics', {})
print(f"✅ Found Nikki: client_id={nikki_id!r}, {len(evals_db)} eval rows in DB")

# ── 2. Recalculate stats fresh from DB evals ─────────────────────────────────
fresh_stats = calculate_statistics(evals_db, None, None)

# ── 3. Fetch the Stats tab from the sheet ────────────────────────────────────
def fetch_tab_csv(sheet_key, gid='0'):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_key}/export?format=csv&gid={gid}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), header=None)

# Try to detect Stats tab GID
def get_gid(sheet_key, fragment):
    try:
        r = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_key}/edit", timeout=20)
        for m in re.finditer(r'"(\d+)"[^"]*"([^"]+)"', r.text):
            if fragment.lower() in m.group(2).lower():
                return m.group(1)
    except Exception as e:
        print(f"  (GID lookup failed: {e})")
    return None

print("\n🔍 Fetching Stats tab from sheet...")
stats_gid = get_gid(SHEET_KEY, 'Stats') or get_gid(SHEET_KEY, 'Summary')
if not stats_gid:
    print("  ⚠️  Could not auto-detect Stats GID — trying gid=0 (first tab)")
    stats_gid = '0'

try:
    stats_sheet = fetch_tab_csv(SHEET_KEY, stats_gid)
    print(f"  ✅ Fetched Stats tab (gid={stats_gid}), {len(stats_sheet)} rows")
except Exception as e:
    print(f"  ❌ Failed to fetch Stats tab: {e}")
    stats_sheet = None

# ── 4. Parse sheet Stats values ──────────────────────────────────────────────
def find_cell_value(df, label_fragment):
    """Scan all cells for a label fragment, return the value in the next non-empty cell on the same row."""
    for _, row in df.iterrows():
        for ci, cell in enumerate(row):
            if isinstance(cell, str) and label_fragment.lower() in cell.lower():
                # Return next non-empty cell on this row
                for val in list(row)[ci+1:]:
                    if pd.notna(val) and str(val).strip():
                        return str(val).strip()
    return None

def pcurr(v):
    if v is None:
        return None
    v = str(v).replace('$','').replace(',','').replace('(','').replace(')','').strip()
    try:
        return float(v)
    except:
        return None

sheet_vals = {}
if stats_sheet is not None:
    labels = [
        ('comp_challenge_fees',  'Challenge Fee'),
        ('comp_hedging_results', 'Hedging Result'),
        ('comp_farming_results', 'Farming Result'),
        ('comp_payouts',         'Payout'),
        ('comp_net',             'Net Profit'),
        ('inp_challenge_fees',   'Challenge Fee'),
        ('inp_hedging_results',  'Hedging Result'),
        ('inp_farming_results',  'Farming Result'),
        ('inp_payouts',          'Payout'),
        ('inp_net',              'Net'),
    ]
    # Print raw sheet for inspection
    print("\n=== RAW STATS TAB (first 40 rows) ===")
    print(stats_sheet.iloc[:40].to_string(index=False))

# ── 5. Fetch Evaluations tab from sheet and recompute ────────────────────────
print("\n🔍 Fetching Evaluations tab from sheet...")
eval_gid = get_gid(SHEET_KEY, 'Evaluations') or get_gid(SHEET_KEY, 'Eval')
if not eval_gid:
    print("  ⚠️  Could not detect Evaluations GID — trying gid=0")
    eval_gid = '0'

try:
    sheet_url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit"
    from utils.data_processor import fetch_sheet_data
    evals_sheet = fetch_sheet_data(sheet_url)
    print(f"  ✅ Fetched {len(evals_sheet)} eval rows from sheet")
except Exception as e:
    print(f"  ❌ fetch_sheet_data failed: {e}")
    evals_sheet = None

# ── 6. Row-by-row hedge comparison ───────────────────────────────────────────
P1_HEDGE_COLS  = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_HEDGE_COLS  = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1',
                  'Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

def row_hedges(ev):
    p1 = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    fd = sum(parse_currency(ev.get(c)) for c in FD_HEDGE_COLS)
    fa = sum(parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS)
    return p1, fd, fa

if evals_sheet is not None:
    print("\n=== ROW-BY-ROW HEDGE COMPARISON (DB vs Sheet) ===")
    print(f"{'#':<4} {'Firm':<20} {'Acct(P1)':<14} {'Status P1':<12} {'Status':<12} "
          f"{'DB P1-H':>10} {'SHT P1-H':>10} {'DB FD-H':>10} {'SHT FD-H':>10} "
          f"{'DB FA-H':>10} {'SHT FA-H':>10}")
    print("-"*130)

    # Match rows by Account # (P1 account)
    sheet_by_acct = {}
    for ev in evals_sheet:
        a = str(ev.get('Account #','')).strip()
        if a:
            sheet_by_acct[a] = ev

    total_db_p1 = total_sht_p1 = 0.0
    total_db_fd = total_sht_fd = 0.0
    total_db_fa = total_sht_fa = 0.0
    unmatched = []

    for i, db_ev in enumerate(evals_db):
        acct = str(db_ev.get('Account #','')).strip()
        sht_ev = sheet_by_acct.get(acct)
        sp1 = str(db_ev.get('Status P1','')).strip()
        sfd = str(db_ev.get('Status') or db_ev.get('Status Funded','')).strip()
        firm = str(db_ev.get('Prop Firm','')).strip()

        db_p1, db_fd, db_fa = row_hedges(db_ev)
        if sht_ev:
            sht_p1, sht_fd, sht_fa = row_hedges(sht_ev)
        else:
            sht_p1 = sht_fd = sht_fa = 0.0
            unmatched.append(acct)

        diff_p1 = db_p1 - sht_p1
        diff_fd = db_fd - sht_fd
        diff_fa = db_fa - sht_fa

        has_diff = abs(diff_p1) > 0.01 or abs(diff_fd) > 0.01 or abs(diff_fa) > 0.01 or not sht_ev

        if has_diff:
            flag = '⚠️ ' if has_diff else '   '
            print(f"{flag}{i+1:<3} {firm:<20} {acct:<14} {sp1:<12} {sfd:<12} "
                  f"{db_p1:>10.2f} {sht_p1:>10.2f} {db_fd:>10.2f} {sht_fd:>10.2f} "
                  f"{db_fa:>10.2f} {sht_fa:>10.2f}")
            if not sht_ev:
                print(f"      ⚠️  No matching sheet row for account {acct!r}")

        total_db_p1  += db_p1;  total_sht_p1  += sht_p1
        total_db_fd  += db_fd;  total_sht_fd  += sht_fd
        total_db_fa  += db_fa;  total_sht_fa  += sht_fa

    print(f"\n{'TOTALS':<4} {'':20} {'':14} {'':12} {'':12} "
          f"{total_db_p1:>10.2f} {total_sht_p1:>10.2f} {total_db_fd:>10.2f} {total_sht_fd:>10.2f} "
          f"{total_db_fa:>10.2f} {total_sht_fa:>10.2f}")
    print(f"  Diffs → P1-hedge:{total_db_p1-total_sht_p1:+.2f}  FD-hedge:{total_db_fd-total_sht_fd:+.2f}  FA-hedge:{total_db_fa-total_sht_fa:+.2f}")

    # Sheet-only rows (in sheet but not in DB)
    db_accts = {str(ev.get('Account #','')).strip() for ev in evals_db}
    sheet_only = [ev for ev in evals_sheet if str(ev.get('Account #','')).strip() not in db_accts]
    if sheet_only:
        print(f"\n⚠️  {len(sheet_only)} rows in SHEET but NOT in DB:")
        for ev in sheet_only:
            sp1,sfd,sfa = row_hedges(ev)
            print(f"   Acct={ev.get('Account #','')}  Firm={ev.get('Prop Firm','')}  "
                  f"P1={sp1:.2f}  FD={sfd:.2f}  FA={sfa:.2f}")

# ── 7. Statistics summary comparison ─────────────────────────────────────────
def fmts(v): return f"${v:,.2f}" if isinstance(v, (int,float)) else str(v)

def compare_stats(label, db_s, fresh_s):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  {'Metric':<25} {'Stored DB':>14} {'Recalculated':>14}")
    print(f"  {'-'*55}")
    for k in ['challenge_fees','hedging_results','farming_results','payouts','net_profit']:
        dv = db_s.get(k, 0)
        fv = fresh_s.get(k, 0)
        diff = fv - dv
        flag = ' ⚠️ ' if abs(diff) > 0.05 else ''
        print(f"  {k:<25} {fmts(dv):>14} {fmts(fv):>14}{flag}")

print("\n\n" + "="*60)
print("  STATISTICS SUMMARY")
compare_stats("Profitability - Completed",
              stats_db.get('profitability_completed', {}),
              fresh_stats.get('profitability_completed', {}))
compare_stats("Cashflow - In Progress",
              stats_db.get('cashflow_inprogress', {}),
              fresh_stats.get('cashflow_inprogress', {}))

if evals_sheet is not None:
    fresh_from_sheet = calculate_statistics(evals_sheet, None, None)
    compare_stats("Profitability - Completed (from SHEET evals)",
                  fresh_stats.get('profitability_completed', {}),
                  fresh_from_sheet.get('profitability_completed', {}))
    compare_stats("Cashflow - In Progress (from SHEET evals)",
                  fresh_stats.get('cashflow_inprogress', {}),
                  fresh_from_sheet.get('cashflow_inprogress', {}))
