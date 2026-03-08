"""
Debug Davvy's Challenge Fees - Completed section.
Dashboard: $31,418.51   Sheet: -$32,357.67 (abs $32,357.67)
Diff: $32,357.67 - $31,418.51 = $939.16 under-counted in dashboard.
"""
import requests, io, sys
sys.path.insert(0, '.')
import pandas as pd
from utils.data_processor import parse_currency
from dashboard.database import get_all_clients

SHEET_KEY = '1eGPlYOTmBEUN0vNwA-IM11IZVS4II_5sDdFrlVJ0xzM'

# ─── 1. Fetch live sheet ──────────────────────────────────────────────────────
print("Fetching Davvy sheet...")
url = f"https://docs.google.com/spreadsheets/d/{SHEET_KEY}/export?format=csv"
r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
r.raise_for_status()

df_raw = pd.read_csv(io.StringIO(r.text), header=None)
header_idx = -1
for i, row in df_raw.head(10).iterrows():
    if row.astype(str).str.contains('Prop Firm', case=False, na=False).any():
        header_idx = i
        break

df = pd.read_csv(io.StringIO(r.text), header=header_idx)
df.columns = [str(c).strip() for c in df.columns]
mask = df['Prop Firm'].notna() & ~df['Prop Firm'].astype(str).str.strip().isin(['', 'nan'])
df = df[mask].reset_index(drop=True)
print(f"Sheet rows: {len(df)}")

# Show status columns available
status_cols = [c for c in df.columns if 'status' in c.lower() or c == 'Status P1']
print(f"Status columns: {status_cols}")

# ─── 2. Replicate sheet SUMIF formula ────────────────────────────────────────
# Sheet formula: (SUMIF(Fee,P1="Fail") + SUMIF(Fee,Status="Completed") + SUMIF(Fee,Status="Fail")) * -1
# We need to know the EXACT column names on the sheet

# Detect fee column
fee_col = 'Fee' if 'Fee' in df.columns else None
act_fee_col = 'Activation Fee' if 'Activation Fee' in df.columns else None
p1_col = 'Status P1' if 'Status P1' in df.columns else None
status_col = 'Status' if 'Status' in df.columns else None
print(f"Fee col: {fee_col!r}  Act Fee col: {act_fee_col!r}  P1 col: {p1_col!r}  Status col: {status_col!r}")

def pf(v): return parse_currency(v)

# SHEET SUMIF logic (exact replication)
sumif_p1_fail    = df[df[p1_col].astype(str).str.strip() == 'Fail'][fee_col].apply(pf).sum() if p1_col and fee_col else 0
sumif_stat_done  = df[df[status_col].astype(str).str.strip() == 'Completed'][fee_col].apply(pf).sum() if status_col and fee_col else 0
sumif_stat_fail  = df[df[status_col].astype(str).str.strip() == 'Fail'][fee_col].apply(pf).sum() if status_col and fee_col else 0

sheet_total_fee = sumif_p1_fail + sumif_stat_done + sumif_stat_fail
print(f"\n=== Sheet fee components (replicating SUMIF) ===")
print(f"  SUMIF(Fee, P1=Fail)          = {sumif_p1_fail:>12,.2f}  ({int(df[df[p1_col].astype(str).str.strip()=='Fail'].shape[0])} rows)")
print(f"  SUMIF(Fee, Status=Completed) = {sumif_stat_done:>12,.2f}  ({int(df[df[status_col].astype(str).str.strip()=='Completed'].shape[0])} rows)")
print(f"  SUMIF(Fee, Status=Fail)      = {sumif_stat_fail:>12,.2f}  ({int(df[df[status_col].astype(str).str.strip()=='Fail'].shape[0])} rows)")
print(f"  RAW TOTAL                    = {sheet_total_fee:>12,.2f}")
print(f"  * -1 (as displayed)          = {-sheet_total_fee:>12,.2f}  ← should be -32,357.67")

# Check for overlapping rows (P1=Fail AND Status=Fail or Status=Completed)
if p1_col and status_col:
    both = df[(df[p1_col].astype(str).str.strip() == 'Fail') & 
              (df[status_col].astype(str).str.strip().isin(['Fail', 'Completed']))]
    if len(both):
        print(f"\n⚠️  {len(both)} rows have BOTH P1=Fail AND Status=Fail/Completed:")
        for _, rw in both.iterrows():
            print(f"   {rw.get('Prop Firm')} | {rw.get('Account #')} | P1={rw.get('Status P1')} | Status={rw.get('Status')} | Fee={rw.get('Fee')}")

# ─── 3. Python code logic on same sheet data ─────────────────────────────────
py_total = 0.0
py_breakdown = []
for _, rw in df.iterrows():
    s_p1 = str(rw.get(p1_col, '')).strip() if p1_col else ''
    s_st = str(rw.get(status_col, '')).strip() if status_col else ''
    if 'deleted' in s_p1.lower() or 'deleted' in s_st.lower():
        continue
    fee = pf(rw.get(fee_col, 0))
    is_p1_fail = s_p1 == 'Fail'
    is_funded_fail = s_st == 'Fail'
    is_funded_completed = s_st == 'Completed'
    added = 0.0
    if is_p1_fail:       added += fee
    if is_funded_fail:   added += fee
    if is_funded_completed: added += fee
    py_total += added
    if added:
        py_breakdown.append((rw.get('Prop Firm'), rw.get('Account #'), s_p1, s_st, fee, added))

print(f"\n=== Python code logic on same sheet data ===")
print(f"  Python total = {py_total:>12,.2f}  ← should match sheet {sheet_total_fee:,.2f}")
print(f"  Diff = {(sheet_total_fee - py_total):>+,.2f}")

# ─── 4. Show all contributing rows and flag mismatches ───────────────────────
print(f"\n=== All rows contributing to completed fees (Python logic) ===")
print(f"{'Firm':<22} {'Account':<32} {'P1':<12} {'Status':<12} {'Fee':>10} {'Added':>10}")
print("-"*105)
for firm, acc, sp1, sst, fee, added in py_breakdown:
    dbl = "  ← DOUBLE" if added > fee + 0.01 else ""
    print(f"{str(firm):<22} {str(acc):<32} {sp1:<12} {sst:<12} {fee:>10,.2f} {added:>10,.2f}{dbl}")

# ─── 5. Check what's on the sheet that Python is MISSING ─────────────────────
sheet_row_fees = {}
for _, rw in df.iterrows():
    s_p1 = str(rw.get(p1_col, '')).strip() if p1_col else ''
    s_st = str(rw.get(status_col, '')).strip() if status_col else ''
    if 'deleted' in s_p1.lower() or 'deleted' in s_st.lower():
        continue
    if s_p1 == 'Fail' or s_st in ('Fail', 'Completed'):
        key = str(rw.get('Account #', ''))
        sheet_row_fees[key] = pf(rw.get(fee_col, 0))

py_row_keys = set(str(acc) for _, acc, _, _, _, _ in py_breakdown)
sheet_keys = set(sheet_row_fees.keys())
missing_from_py = sheet_keys - py_row_keys
extra_in_py = py_row_keys - sheet_keys
print(f"\n=== Keys in sheet but NOT in Python: {missing_from_py}")
print(f"=== Keys in Python but NOT on sheet: {extra_in_py}")

# ─── 6. Check DB vs sheet ─────────────────────────────────────────────────────
print(f"\n=== Loading DB data for comparison ===")
all_clients = get_all_clients()
davvy_id = None
for cid in all_clients:
    if 'davy' in str(cid).lower() or 'davvy' in str(cid).lower():
        davvy_id = cid
        break

if davvy_id:
    evs = all_clients[davvy_id].get('evaluations', [])
    stats = all_clients[davvy_id].get('statistics', {})
    pc = stats.get('profitability_completed', {})
    print(f"DB stored challenge_fees (completed) = {pc.get('challenge_fees', 0):,.2f}")
    print(f"Sheet expects (abs)                  = {sheet_total_fee:,.2f}")
    print(f"Diff = {(sheet_total_fee - pc.get('challenge_fees', 0)):+,.2f}")
    
    # Show DB fee values for all rows with relevant statuses
    print(f"\n=== DB rows with fees (relevant statuses) ===")
    for ev in evs:
        s_p1 = str(ev.get('Status P1', '')).strip()
        s_st = str(ev.get('Status', '') or ev.get('Status Funded', '')).strip()
        if s_p1 == 'Fail' or s_st in ('Fail', 'Completed'):
            fee = pf(ev.get('Fee', 0))
            act = pf(ev.get('Activation Fee', 0))
            print(f"  {ev.get('Prop Firm','?'):<22} {str(ev.get('Account #','')):<32} P1={s_p1:<8} St={s_st:<10} fee={fee:>8,.2f}  actfee={act:>8,.2f}")
else:
    print("Davvy not found in DB")
    print("Available clients:", list(all_clients.keys()))
