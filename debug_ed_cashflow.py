"""
Compare Ed's cashflow_inprogress stats from local DB vs Google Sheet.
"""
import sys, json
sys.path.insert(0, '.')
from dashboard.database import get_connection, get_all_clients
from utils.data_processor import parse_currency, calculate_statistics
import requests
from io import StringIO
import pandas as pd

SHEET_URL = "https://docs.google.com/spreadsheets/d/1ivVtySJKJveJHNg9Hs4kH8fTqWDgMQMOxkYCPxIMtQM/edit?usp=sharing"
KEY = "1ivVtySJKJveJHNg9Hs4kH8fTqWDgMQMOxkYCPxIMtQM"

# ── 1. Load Ed's stored stats from DB ─────────────────────────────────────────
all_clients = get_all_clients()
ed_data = None
for cid, data in all_clients.items():
    if 'ed' in str(cid).lower() or 'ed' in str(data.get('identity', {}).get('name', '')).lower():
        ed_data = data
        print(f"Found client: {cid}")
        break

if not ed_data:
    print("Ed not found. Listing all clients:")
    for cid in all_clients:
        print(f"  {cid}: {all_clients[cid].get('identity', {})}")
    sys.exit(1)

stored_stats = ed_data.get('statistics', {})
ci = stored_stats.get('cashflow_inprogress', {})
print("\n=== DB Stored: cashflow_inprogress ===")
for k, v in ci.items():
    print(f"  {k}: ${v:,.2f}")

# ── 2. Fetch Stats tab from Ed's sheet ─────────────────────────────────────────
print("\n=== Fetching Stats tab from Ed's sheet ===")
stats_gid = None

# Try to find the Stats tab GID
try:
    # First grab the sheet metadata to find stat tab
    meta_url = f"https://docs.google.com/spreadsheets/d/{KEY}/edit"
    # Try known GIDs or just try default (0) and a few others
    for gid in [0, '0', '839895136', '1', '965866889']:
        test_url = f"https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={gid}"
        r = requests.get(test_url, timeout=15)
        if r.status_code == 200:
            lines = r.text.strip().split('\n')[:20]
            content = ' '.join(lines[:5])
            if 'Profitability' in content or 'Challenge Fees' in content or 'Cashflow' in content or 'In Progress' in content:
                print(f"  Found Stats tab at GID={gid}")
                for i, line in enumerate(lines[:20]):
                    print(f"    [{i}] {line[:120]}")
                stats_gid = gid
                break
            else:
                pass  # not stats tab
except Exception as e:
    print(f"Error fetching stats tab: {e}")

# ── 3. Live recompute from stored evaluations ───────────────────────────────────
evals = ed_data.get('evaluations', [])
print(f"\n=== Live recompute from {len(evals)} stored evaluations ===")

# Check all fees
total_fee = sum(parse_currency(ev.get('Fee')) for ev in evals)
print(f"Sum of all Fee values (raw): ${total_fee:,.2f}")
print(f"DB stored challenge_fees:    ${ci.get('challenge_fees', 0):,.2f}")

# Check status breakdown and fee contribution
from utils.data_processor import parse_currency as pc
print("\nFee breakdown by status:")
groups = {}
for ev in evals:
    sp1 = str(ev.get('Status P1', '')).strip()
    sf = str(ev.get('Status', '') or ev.get('Status Funded', '')).strip()
    fee = parse_currency(ev.get('Fee'))
    act = parse_currency(ev.get('Activation Fee'))
    key = f"P1={sp1}, Status={sf}"
    if key not in groups:
        groups[key] = {'count': 0, 'fee': 0.0, 'act': 0.0}
    groups[key]['count'] += 1
    groups[key]['fee'] += fee
    groups[key]['act'] += act

for k, v in sorted(groups.items(), key=lambda x: -x[1]['fee']):
    print(f"  {k}: fee=${v['fee']:,.2f}  act=${v['act']:,.2f}  N={v['count']}")

print(f"\nTotal fee (all rows):       ${sum(v['fee'] for v in groups.values()):,.2f}")
print(f"Total act (all rows):       ${sum(v['act'] for v in groups.values()):,.2f}")
