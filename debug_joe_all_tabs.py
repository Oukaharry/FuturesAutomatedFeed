"""
Joe's sheet might have MULTIPLE evaluation tabs (Joe + Davvy combined).
Let's discover all sheet tabs and try fetching each one looking for evaluation data.
"""
import sys, re, requests
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')

import pandas as pd
from io import StringIO

SHEET_KEY = "1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4"

# --- Step 1: Get all tab GIDs by fetching export index ---
print("=== DISCOVERING ALL TABS ===")

# Try fetching the spreadsheet HTML to find GIDs and names
try:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit"
    resp = requests.get(url, timeout=10)
    content = resp.text

    # Multiple patterns to try
    # Pattern 1: "gid=XXXXXXX" in URLs
    gids_from_urls = re.findall(r'[?&]gid=(\d+)', content)
    
    # Pattern 2: sheet tab data in JSON-like structure
    # Look for tab "name" near "id"
    
    # Pattern 3: A simpler approach - look for the JSON that defines sheets
    # Google Sheets embeds sheet info as: ["name","id","type"...]
    sheet_data = re.findall(r'\["([^"]+)",\s*null,\s*(\d+)', content)
    
    print(f"GIDs found in URLs: {sorted(set(gids_from_urls))}")
    print(f"Tab data from pattern: {sheet_data[:20]}")
    
except Exception as e:
    print(f"Error: {e}")

# --- Step 2: Try common GIDs systematically ---
print()
print("=== TRYING TO FETCH EACH DISCOVERED GID ===")
gids_to_try = list(set(gids_from_urls)) if gids_from_urls else []

# Always try GID=0 (first sheet)
if '0' not in gids_to_try:
    gids_to_try.insert(0, '0')

evaluations_tabs = []

for gid in sorted(gids_to_try, key=lambda x: int(x)):
    try:
        csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv&gid={gid}"
        resp = requests.get(csv_url, timeout=10)
        if resp.status_code != 200 or '<html' in resp.text.lower():
            print(f"  GID={gid:>12}: failed (status={resp.status_code})")
            continue
        
        # Check if it looks like an evaluations tab
        first_500 = resp.text[:500]
        has_prop_firm = 'Prop Firm' in first_500 or 'prop firm' in first_500.lower()
        has_account_size = 'Account Size' in first_500
        has_status = 'Status' in first_500
        has_fee = 'Fee' in first_500
        
        # Find header
        df = pd.read_csv(StringIO(resp.text), header=None, nrows=5)
        preview = str(df.head(3).to_dict())[:200]
        
        row_count = resp.text.count('\n')
        
        print(f"  GID={gid:>12}: rows~{row_count:4d} | PropFirm={has_prop_firm} AccountSize={has_account_size} | preview={preview[:100]}")
        
        if has_prop_firm or has_account_size:
            evaluations_tabs.append(gid)
    except Exception as e:
        print(f"  GID={gid:>12}: error {e}")

print()
print(f"=== EVALUATION TABS FOUND: {evaluations_tabs} ===")

# --- Step 3: For each evaluation tab, compute profitability_completed ---
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

all_evals = []
for gid in evaluations_tabs:
    sheet_url_with_gid = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit#gid={gid}"
    print(f"\nFetching evaluations for GID={gid}...")
    result = fetch_evaluations(sheet_url_with_gid)
    evals = result[0] if isinstance(result, tuple) else result
    print(f"  Rows: {len(evals)}")
    if evals:
        # Status breakdown
        statuses = {}
        for ev in evals:
            sp1 = str(ev.get('Status P1', '')).strip()
            sf  = str(ev.get('Status', '')).strip()
            key = f"P1={sp1}, Status={sf}"
            statuses[key] = statuses.get(key, 0) + 1
        for k, v in sorted(statuses.items(), key=lambda x: -x[1])[:5]:
            print(f"    {k}: {v}")
        all_evals.extend(evals)

print()
print(f"=== COMBINED ({len(all_evals)} total rows) ===")
if all_evals:
    stats = calculate_statistics(all_evals, None, None)
    prof = stats['profitability_completed']
    print(f"  Challenge Fees:  ${prof['challenge_fees']:>12,.2f}  (sheet shows: $45,242.39)")
    print(f"  Hedging Results: ${prof['hedging_results']:>12,.2f}  (sheet shows: -$42,160.47)")
    print(f"  Farming Results: ${prof['farming_results']:>12,.2f}  (sheet shows: $15,034.28)")
    print(f"  Payouts:         ${prof['payouts']:>12,.2f}  (sheet shows: $100,189.00)")
    print(f"  Net Profit:      ${prof['net_profit']:>12,.2f}  (sheet shows: $27,057.53)")
