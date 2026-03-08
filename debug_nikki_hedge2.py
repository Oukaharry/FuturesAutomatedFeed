"""
Nikki sheet vs DB hedge comparison — v2
Uses fetch_evaluations() and parses the Stats tab directly.
"""
import sys, json, re, io
sys.path.insert(0, '.')
import requests
import pandas as pd
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency, calculate_statistics, fetch_evaluations

SHEET_KEY  = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'
SHEET_URL  = f'https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit'

P1_HEDGE_COLS  = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
FD_HEDGE_COLS  = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1',
                  'Hedge Result 4.1','Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 35)]

# ── 1. Nikki in DB ────────────────────────────────────────────────────────────
all_clients = get_all_clients()
nikki_id    = 'Nikki'
nikki_data  = all_clients[nikki_id]
evals_db    = nikki_data.get('evaluations', [])
stats_db    = nikki_data.get('statistics', {})
print(f"DB rows: {len(evals_db)}")

# ── 2. Fetch evaluations from sheet ───────────────────────────────────────────
print("Fetching sheet evaluations...")
result = fetch_evaluations(SHEET_URL)
evals_sheet = result[0] if isinstance(result, tuple) else result
print(f"Sheet rows: {len(evals_sheet)}")

# ── 3. Recalculate stats from both sources ────────────────────────────────────
stats_from_db     = calculate_statistics(evals_db,     None, None)
stats_from_sheet  = calculate_statistics(evals_sheet,  None, None)

# ── 4. Try to fetch Stats tab values directly from sheet ─────────────────────
def all_gids(sheet_key):
    """Return dict of {tab_name: gid} from the sheet."""
    try:
        r = requests.get(f'https://docs.google.com/spreadsheets/d/{sheet_key}/edit', timeout=20)
        # Modern sheets embed sheet metadata as JSON
        names = re.findall(r'"name":"([^"]+)".*?"id":(\d+)', r.text)
        by_id  = re.findall(r'"gid=(\d+)"', r.text)
        # Try the scriptData JSON blob
        m = re.search(r'bootstrapData\s*=\s*(.+?);\s*</script>', r.text, re.DOTALL)
        tabs = {}
        for m2 in re.finditer(r'"(\d+)","(?:[^"]*?)"(?:.*?)"name":"([^"]+)"', r.text):
            tabs[m2.group(2)] = m2.group(1)
        if not tabs:
            for m2 in re.finditer(r'gid=(\d+)[^"]*"[^"]*"([^"]{3,40})"', r.text):
                tabs[m2.group(2)] = m2.group(1)
        return tabs
    except Exception as e:
        print(f"  GID lookup error: {e}")
        return {}

tabs = all_gids(SHEET_KEY)
print(f"\nSheet tabs found: {tabs}")

stats_gid = None
for name, gid in tabs.items():
    if 'stat' in name.lower() or 'summar' in name.lower() or 'dashboard' in name.lower():
        stats_gid = gid
        print(f"  → Using Stats tab: {name!r} gid={gid}")
        break

sheet_stats_values = {}
if stats_gid:
    try:
        url = f'https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv&gid={stats_gid}'
        r = requests.get(url, timeout=20)
        df = pd.read_csv(io.StringIO(r.text), header=None)
        print(f"\n=== Stats tab raw (first 30 rows) ===")
        print(df.iloc[:30].to_string(index=False))

        def find_val(df, kw):
            for _, row in df.iterrows():
                for i, cell in enumerate(row):
                    if isinstance(cell, str) and kw.lower() in cell.lower():
                        for v in list(row)[i+1:]:
                            if pd.notna(v) and str(v).strip():
                                s = str(v).replace('$','').replace(',','').replace('(','').replace(')','').strip()
                                try: return float(s)
                                except: continue
            return None

        for k, kw in [
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
        ]:
            sheet_stats_values[k] = find_val(df, kw)
    except Exception as e:
        print(f"Stats tab fetch error: {e}")

# ── 5. Row-level hedge comparison ─────────────────────────────────────────────
def row_hedges(ev):
    p1 = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
    fd = sum(parse_currency(ev.get(c)) for c in FD_HEDGE_COLS)
    fa = sum(parse_currency(ev.get(c)) for c in HEDGE_DAY_COLS)
    return p1, fd, fa

sheet_by_acct = {}
for ev in evals_sheet:
    a = str(ev.get('Account #','')).strip()
    if a:
        sheet_by_acct[a] = ev

print(f"\n=== ROW DIFFS (DB vs Sheet) — only rows with hedge differences ===")
print(f"{'#':<4} {'Firm':<20} {'Account':<16} {'SP1':<8} {'SFD':<12}"
      f" {'DB_P1':>9} {'SHT_P1':>9} {'Δ_P1':>9}"
      f" {'DB_FD':>9} {'SHT_FD':>9} {'Δ_FD':>9}"
      f" {'DB_FA':>9} {'SHT_FA':>9} {'Δ_FA':>9}")
print('-'*155)

tot = {'db_p1':0,'sht_p1':0,'db_fd':0,'sht_fd':0,'db_fa':0,'sht_fa':0}
diffs = []

for i, db_ev in enumerate(evals_db):
    acct  = str(db_ev.get('Account #','')).strip()
    sht_ev = sheet_by_acct.get(acct)
    sp1   = str(db_ev.get('Status P1','')).strip()
    sfd   = str(db_ev.get('Status') or db_ev.get('Status Funded','')).strip()
    firm  = str(db_ev.get('Prop Firm','')).strip()

    dp1, dfd, dfa = row_hedges(db_ev)
    sp1v, sfd_v, sfa = (row_hedges(sht_ev) if sht_ev else (0.0, 0.0, 0.0))

    Δp1 = dp1 - sp1v
    Δfd = dfd - sfd_v
    Δfa = dfa - sfa

    tot['db_p1']  += dp1;  tot['sht_p1']  += sp1v
    tot['db_fd']  += dfd;  tot['sht_fd']  += sfd_v
    tot['db_fa']  += dfa;  tot['sht_fa']  += sfa

    if abs(Δp1)>0.01 or abs(Δfd)>0.01 or abs(Δfa)>0.01 or not sht_ev:
        diffs.append((i, firm, acct, sp1, sfd, dp1, sp1v, Δp1, dfd, sfd_v, Δfd, dfa, sfa, Δfa, not sht_ev))
        print(f"{i+1:<4} {firm:<20} {acct:<16} {sp1:<8} {sfd:<12}"
              f" {dp1:>9.2f} {sp1v:>9.2f} {Δp1:>+9.2f}"
              f" {dfd:>9.2f} {sfd_v:>9.2f} {Δfd:>+9.2f}"
              f" {dfa:>9.2f} {sfa:>9.2f} {Δfa:>+9.2f}"
              + (' ← NO SHEET MATCH' if not sht_ev else ''))

print(f"\n{'TOTALS':<4} {'':20} {'':16} {'':8} {'':12}"
      f" {tot['db_p1']:>9.2f} {tot['sht_p1']:>9.2f} {tot['db_p1']-tot['sht_p1']:>+9.2f}"
      f" {tot['db_fd']:>9.2f} {tot['sht_fd']:>9.2f} {tot['db_fd']-tot['sht_fd']:>+9.2f}"
      f" {tot['db_fa']:>9.2f} {tot['sht_fa']:>9.2f} {tot['db_fa']-tot['sht_fa']:>+9.2f}")

# Sheet rows not in DB
db_accts = {str(ev.get('Account #','')).strip() for ev in evals_db}
sheet_only = [ev for ev in evals_sheet if str(ev.get('Account #','')).strip() not in db_accts]
if sheet_only:
    print(f"\n⚠️  {len(sheet_only)} rows in SHEET but NOT in DB:")
    for ev in sheet_only[:20]:
        sp1v, sfd_v, sfa = row_hedges(ev)
        print(f"   {ev.get('Account #','-'):<18} {ev.get('Prop Firm','-'):<20}  P1={sp1v:.2f}  FD={sfd_v:.2f}  FA={sfa:.2f}")

# ── 6. Statistics table ───────────────────────────────────────────────────────
def fmts(v):
    if v is None: return '    N/A'
    return f"{v:>12,.2f}" if v >= 0 else f"{v:>12,.2f}"

def compare_block(title, db_s, sheet_s):
    print(f"\n{'='*68}")
    print(f"  {title}")
    print(f"  {'Metric':<25} {'DB (stored)':>13} {'DB (sheet evls)':>16} {'Δ':>10}")
    print(f"  {'-'*64}")
    for k in ['challenge_fees','hedging_results','farming_results','payouts','net_profit']:
        dv = db_s.get(k, 0)
        sv = sheet_s.get(k, 0)
        d  = sv - dv
        flag = '  ⚠️' if abs(d)>0.05 else ''
        print(f"  {k:<25} {fmts(dv)} {fmts(sv)} {d:>+10.2f}{flag}")

compare_block("Profitability - Completed  (DB stored vs recalc from sheet evals)",
              stats_db.get('profitability_completed', {}),
              stats_from_sheet.get('profitability_completed', {}))
compare_block("Cashflow - In Progress  (DB stored vs recalc from sheet evals)",
              stats_db.get('cashflow_inprogress', {}),
              stats_from_sheet.get('cashflow_inprogress', {}))

print(f"\n  DB row count : {len(evals_db)}")
print(f"  Sheet row count: {len(evals_sheet)}")
print(f"  Rows in DB not in sheet: {len([e for e in evals_db if str(e.get('Account #','')).strip() not in sheet_by_acct])}")
print(f"  Rows in sheet not in DB: {len(sheet_only)}")
