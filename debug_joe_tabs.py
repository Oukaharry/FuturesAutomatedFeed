"""
1. Try to fetch Joe's Stats tab from the sheet
2. Analyse what the Hedge Net columns actually contain vs individual results
"""
import sys, re
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

import requests
import pandas as pd
from io import StringIO
from utils.data_processor import parse_currency, _fetch_gid_for_tab
from dashboard.database import get_all_clients

SHEET_KEY = "1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4"

# --- Try to get all tab GIDs ---
print("=== DISCOVERING SHEET TABS ===")
try:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit"
    resp = requests.get(url, timeout=10)
    content = resp.text
    # Find tab names & GIDs
    tab_pattern = re.findall(r'"(\d+)","([^"]{2,40})"', content)
    seen = set()
    tabs = []
    for gid, name in tab_pattern:
        if name not in seen and not name.startswith('\\'):
            seen.add(name)
            tabs.append((gid, name))
    if tabs:
        for gid, name in tabs[:30]:
            print(f"  GID={gid:>12} | {name}")
    else:
        print("  Could not discover tabs (auth required?)")
except Exception as e:
    print(f"  Error: {e}")

# --- Fetch Stats tab if it exists ---
print()
stats_tab_gids = []
for tab_name in ['Stats', 'Summary', 'Statistics', 'Overview', 'Profitability']:
    gid = _fetch_gid_for_tab(SHEET_KEY, tab_name)
    if gid:
        print(f"Found '{tab_name}' tab with GID={gid}")
        stats_tab_gids.append((tab_name, gid))
    else:
        print(f"Tab '{tab_name}': not found")

for tab_name, gid in stats_tab_gids:
    print(f"\n=== FETCHING {tab_name} TAB (GID={gid}) ===")
    try:
        csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv&gid={gid}"
        resp = requests.get(csv_url, timeout=15)
        if resp.status_code == 200 and '<html' not in resp.text.lower():
            df = pd.read_csv(StringIO(resp.text), header=None)
            print(df.to_string(max_rows=40, max_cols=10))
        else:
            print(f"  Failed to fetch (status={resp.status_code})")
    except Exception as e:
        print(f"  Error: {e}")

# --- Analyse Hedge Net vs individual Hedge Results for Joe ---
print()
print("=== HEDGE NET vs INDIVIDUAL COLUMNS FOR JOE ===")
all_clients = get_all_clients()
joe_data = all_clients.get('Joe')
if joe_data:
    evals = [ev for ev in (joe_data.get('evaluations') or []) if isinstance(ev, dict)]

    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    total_hedgenet_p1 = 0.0
    total_hedgenet_funded = 0.0
    total_individual_p1 = 0.0
    total_individual_funded = 0.0
    total_fees = 0.0
    status_counts = {}

    for ev in evals:
        sp1 = str(ev.get('Status P1', '')).strip()
        sf  = str(ev.get('Status', '')).strip()
        key = f"P1={sp1}, Status={sf}"
        status_counts[key] = status_counts.get(key, 0) + 1

        fee = parse_currency(ev.get('Fee'))
        hn  = parse_currency(ev.get('Hedge Net'))
        hn1 = parse_currency(ev.get('Hedge Net.1'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        fdh = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
        payouts = sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1,5))

        total_hedgenet_p1     += hn
        total_hedgenet_funded += hn1
        total_individual_p1   += p1h
        total_individual_funded += fdh
        total_fees += fee

    print(f"  Total fees:                  ${total_fees:>12,.2f}")
    print(f"  Sum Hedge Net (P1):          ${total_hedgenet_p1:>12,.2f}  (includes -fee for P1=Fail rows)")
    print(f"  Sum Hedge Net.1 (Funded):    ${total_hedgenet_funded:>12,.2f}  (includes -fee for funded ended)")
    print(f"  sheet_hedge_total:           ${total_hedgenet_p1 + total_hedgenet_funded:>12,.2f}")
    print(f"  Sum Individual P1 Results:   ${total_individual_p1:>12,.2f}  (raw hedge results, no fee)")
    print(f"  Sum Individual Funded:       ${total_individual_funded:>12,.2f}  (raw hedge results, no fee)")
    print()
    print(f"  Profitability Completed:")
    print(f"    Code: uses Individual P1+Funded for P1=Fail rows = ${total_individual_p1:>12,.2f}")
    print()
    print(f"  Status breakdown for Joe:")
    for k, v in sorted(status_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"    {k}: {v}")

    # Find rows where Hedge Net != sum(Hedge Result 1-5) - fee
    print()
    print("  Checking Hedge Net accuracy (P1=Fail rows only):")
    mismatch_count = 0
    for ev in evals:
        sp1 = str(ev.get('Status P1', '')).strip()
        if sp1 != 'Fail':
            continue
        hn  = parse_currency(ev.get('Hedge Net'))
        fee = parse_currency(ev.get('Fee'))
        p1h = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
        expected_hn = -fee + p1h
        if abs(hn - expected_hn) > 0.01:
            mismatch_count += 1
            firm = ev.get('Prop Firm', '?')
            acct = ev.get('Account #', '?')
            print(f"    MISMATCH: {firm}/{acct}: HedgeNet={hn:.2f}, Expected(-fee+p1h)={expected_hn:.2f}")
    if mismatch_count == 0:
        print("    All Hedge Net values match expected formula.")
