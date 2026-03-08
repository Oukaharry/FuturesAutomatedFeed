"""
Debug Davy's completed challenge fees: DB vs Google Sheet.
Sheet: https://docs.google.com/spreadsheets/d/1eGPlYOTmBEUN0vNwA-IM11IZVS4II_5sDdFrlVJ0xzM
"""
import sys, io, requests
sys.path.insert(0, '.')
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency

SHEET_KEY = '1eGPlYOTmBEUN0vNwA-IM11IZVS4II_5sDdFrlVJ0xzM'

# ── 1. Find Davy ──────────────────────────────────────────────────────────────
all_clients = get_all_clients()
davy_id = None
for cid, data in all_clients.items():
    if 'davy' in str(cid).lower() or 'davy' in str(data.get('client', '')).lower():
        davy_id = cid
        print(f"Found: id={cid}  name={data.get('client')}")
        break

if not davy_id:
    print("Not found. All clients:")
    for cid, d in all_clients.items():
        print(f"  {cid}: {d.get('client','?')}")
    sys.exit(0)

evaluations = all_clients[davy_id].get('evaluations', [])
print(f"{len(evaluations)} evaluations in DB\n")

# ── 2. Reproduce the completed challenge_fees calculation from data_processor ──
# Mirrors calculate_derived_metrics logic for each row
def get_val(row, key):
    val = row.get(key, 0)
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    import re
    s = str(val).replace('$','').replace(' ','').strip()
    if ',' in s:
        if '.' not in s:
            if re.search(r',\d{1,2}$', s): return 0.0
            s = s.replace(',','')
        else:
            if re.search(r',\.', s): return 0.0
            s = s.replace(',','')
    if s in ('', '-'): return 0.0
    try: return float(s)
    except: return 0.0

print("=== DB: Per-eval challenge fee breakdown (Completed only) ===")
db_total_completed  = 0.0
db_total_inprogress = 0.0
for i, ev in enumerate(evaluations):
    status = str(ev.get('Status', '')).strip()
    p1     = str(ev.get('Phase 1 Status', '')).strip()
    fee         = get_val(ev, 'Fee')
    act_fee     = get_val(ev, 'Activation Fee')
    prop_firm   = ev.get('Prop Firm', f'eval_{i}')
    account     = ev.get('Account #', '')

    is_completed = (status == 'Completed')
    is_inprog    = (status not in ('Completed', 'Fail', 'Failed'))

    # HR1-5
    hr_vals = [get_val(ev, f'Hedge Result {j}') for j in range(1, 6)]
    hr_sum  = sum(hr_vals)

    # Phase 1 hedge
    p1_hr = sum(get_val(ev, f'Hedge Result {j}') for j in range(1, 6))

    row_fee_completed = 0.0
    row_fee_inprog    = 0.0

    if is_completed:
        row_fee_completed = fee + act_fee
    elif p1 in ('Pass', 'Completed') and status == 'Fail':
        # P1 passed but account failed — fee still counted?
        row_fee_completed = fee + act_fee

    if is_inprog:
        row_fee_inprog = fee + act_fee

    if row_fee_completed != 0 or row_fee_inprog != 0:
        print(f"  [{i:>3}] {prop_firm:<25} {account:<30} status={status:<12} p1={p1:<12} "
              f"fee={fee:>10.2f} act={act_fee:>8.2f}  "
              f"cmpl={row_fee_completed:>10.2f}  prog={row_fee_inprog:>10.2f}")
    db_total_completed  += row_fee_completed
    db_total_inprogress += row_fee_inprog

print(f"\nDB completed challenge fees total : {db_total_completed:>12.2f}")
print(f"DB inprogress challenge fees total: {db_total_inprogress:>12.2f}")
print(f"Sheet shows (Profitability-Completed): -$32,357.67")
print(f"Diff: {db_total_completed - (-32357.67):>+.2f}")

# ── 3. Fetch the sheet and compute the same ──────────────────────────────────
import pandas as pd
print(f"\n=== Fetching sheet {SHEET_KEY} ===")
url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv"
r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
r.raise_for_status()

df_raw = pd.read_csv(io.StringIO(r.text), header=None)
header_idx = -1
for idx, row in df_raw.head(10).iterrows():
    if row.astype(str).str.contains('Prop Firm', case=False, na=False).any():
        header_idx = idx
        break

if header_idx == -1:
    print("Header not found — showing raw top rows:")
    print(df_raw.head(4).to_string())
    sys.exit(0)

df = pd.read_csv(io.StringIO(r.text), header=header_idx)
df.columns = [str(c).strip() for c in df.columns]
mask = df['Prop Firm'].notna() & ~df['Prop Firm'].astype(str).str.strip().isin(['', 'nan'])
df_data = df[mask].reset_index(drop=True)
print(f"Sheet data rows: {len(df_data)}")

# Show fee & activation fee columns
fee_cols = [c for c in df.columns if 'fee' in c.lower() or 'Fee' in c]
print(f"Fee-related columns: {fee_cols}")

# Compute sheet totals
sheet_completed = 0.0
sheet_inprog    = 0.0
print("\n=== Sheet: rows with non-zero fees (Completed/InProgress) ===")
for _, srow in df_data.iterrows():
    status = str(srow.get('Status', '')).strip()
    p1     = str(srow.get('Phase 1 Status', '')).strip()
    fee    = parse_currency(srow.get('Fee', 0))
    act    = parse_currency(srow.get('Activation Fee', 0))
    pf     = srow.get('Prop Firm', '')
    acc    = srow.get('Account #', '')

    is_completed = (status == 'Completed')
    is_inprog    = (status not in ('Completed', 'Fail', 'Failed'))

    rc = (fee + act) if (is_completed or (p1 in ('Pass','Completed') and status == 'Fail')) else 0.0
    ri = (fee + act) if is_inprog else 0.0

    if rc != 0 or ri != 0:
        print(f"  {pf:<25} {acc:<30} {status:<12} {p1:<12} fee={fee:>10.2f} act={act:>8.2f}  cmpl={rc:>10.2f}  prog={ri:>10.2f}")
    sheet_completed += rc
    sheet_inprog    += ri

print(f"\nSheet-computed completed challenge fees: {sheet_completed:>12.2f}")
print(f"Sheet-computed inprogress challenge fees: {sheet_inprog:>12.2f}")
print(f"\n=== SUMMARY ===")
print(f"DB total completed fees  : {db_total_completed:>12.2f}")
print(f"Sheet total completed fees: {sheet_completed:>12.2f}")
print(f"Gap: {db_total_completed - sheet_completed:>+.2f}")
