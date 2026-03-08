"""
Debug Watkins farming data: compare local DB vs Google Sheet hedge days 1-34.
Sheet key from user-provided URL.
"""
import json, requests, io, sys
sys.path.insert(0, '.')
from dashboard.database import get_all_clients, get_connection
from utils.data_processor import parse_currency

SHEET_KEY = '1u1hFxsLqhz1N5pXcKJCOIY010CIvOxoN_EjpytqWPIo'

# ── 1. Find Watkins in the DB ──────────────────────────────────────────────────
all_clients = get_all_clients()
watkins_id = None
for cid, data in all_clients.items():
    if 'atkin' in str(cid).lower() or 'atkin' in str(data.get('client', '')).lower():
        watkins_id = cid
        print(f"Found Watkins: id={cid}")
        break

if not watkins_id:
    print("No Watkins found. Available clients:")
    for cid, data in all_clients.items():
        print(f"  {cid}: {data.get('client','unknown')}")
    sys.exit(0)

watkins_data = all_clients[watkins_id]
evaluations = watkins_data.get('evaluations', [])
print(f"{len(evaluations)} evaluations in local DB")

# ── 2. Local DB hedge day values ────────────────────────────────────────────
print("\n=== LOCAL DB: Hedge Day 1-34 per evaluation ===")
for i, ev in enumerate(evaluations):
    prop_firm = ev.get('Prop Firm', f'eval_{i}')
    account   = ev.get('Account #', '')
    status    = ev.get('Status', '')
    db_days   = {}
    for d in range(1, 35):
        val = ev.get(f'Hedge Day {d}')
        if val not in (None, '', '0', 0, 'nan'):
            db_days[d] = val
    total_db = sum(parse_currency(v) for v in db_days.values())
    max_day = max(db_days.keys()) if db_days else 0
    print(f"  [{i}] {prop_firm} | {account} | {status}")
    print(f"       DB days: max={max_day}, count={len(db_days)}, total={total_db:+.2f}")
    if db_days:
        print(f"       {db_days}")

# ── 3. Fetch sheet tabs to find the right GID ──────────────────────────────
print(f"\n=== FETCHING SHEET {SHEET_KEY} ===")

# Try the default tab first (no gid), then export with gid=0
import pandas as pd

def fetch_csv(key, gid=None):
    gid_param = f"&gid={gid}" if gid is not None else ""
    url = f"https://docs.google.com/spreadsheets/d/{key}/export?format=csv{gid_param}"
    r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    return r.text

def parse_sheet(csv_text):
    df_raw = pd.read_csv(io.StringIO(csv_text), header=None)
    header_idx = -1
    for i, row in df_raw.head(10).iterrows():
        if row.astype(str).str.contains('Prop Firm', case=False, na=False).any():
            header_idx = i
            break
    if header_idx == -1:
        return None, df_raw
    df = pd.read_csv(io.StringIO(csv_text), header=header_idx)
    df.columns = [str(c).strip() for c in df.columns]
    return df, None

csv_text = fetch_csv(SHEET_KEY)
df, debug_df = parse_sheet(csv_text)

if df is None:
    print("Could not find header row. First 3 rows:")
    print(debug_df.head(3).to_string())
    sys.exit(0)

print(f"Header found. Sheet has {len(df)} rows, {len(df.columns)} cols")

# Show all hedge day cols present in sheet
hedge_cols = [c for c in df.columns if 'Hedge Day' in c and 'Note' not in c]
print(f"Hedge Day columns on sheet: {hedge_cols}")

# Show the sheet column indices for farming days
print("\n=== Sheet column indices for farming ===")
for ci, col in enumerate(df.columns):
    if 'Hedge Day' in col or 'Prop Day' in col or 'Farming' in col:
        print(f"  col[{ci:>3}] = {col!r}")

# ── 4. Sheet hedge day values per data row ──────────────────────────────────
mask = df['Prop Firm'].notna() & (df['Prop Firm'].astype(str).str.strip().isin(['', 'nan']) == False)
df_data = df[mask].reset_index(drop=True)
print(f"\nData rows on sheet: {len(df_data)}")

print("\n=== SHEET: Hedge Day 1-34 per row ===")
for i, srow in df_data.iterrows():
    prop_firm = srow.get('Prop Firm', f'row_{i}')
    account   = str(srow.get('Account #', '')).strip()
    status    = str(srow.get('Status', '')).strip()
    sheet_days = {}
    for d in range(1, 35):
        col = f'Hedge Day {d}'
        if col in df.columns:
            val = str(srow.get(col, '')).strip()
            if val not in ('', 'nan', '0'):
                sheet_days[d] = val
    total_sheet = sum(parse_currency(v) for v in sheet_days.values())
    max_day = max(sheet_days.keys()) if sheet_days else 0
    print(f"  [{i}] {prop_firm} | {account} | {status}")
    print(f"       Sheet days: max={max_day}, count={len(sheet_days)}, total={total_sheet:+.2f}")
    if sheet_days:
        print(f"       {sheet_days}")

# ── 5. Side-by-side comparison (DB vs Sheet) ────────────────────────────────
print("\n=== COMPARISON: DB total vs Sheet total per eval ===")
print(f"{'#':<4} {'Prop Firm':<25} {'DB total':>12} {'Sheet total':>12} {'diff':>10}")
print("-" * 70)
for i, ev in enumerate(evaluations):
    prop_firm = ev.get('Prop Firm', f'eval_{i}')
    account   = str(ev.get('Account #', '')).strip()
    db_total  = sum(parse_currency(ev.get(f'Hedge Day {d}', 0)) for d in range(1, 35))
    
    # Match sheet row by account or prop firm
    sheet_total = None
    for _, srow in df_data.iterrows():
        s_acc = str(srow.get('Account #', '')).strip()
        s_pf  = str(srow.get('Prop Firm', '')).strip()
        if (account and s_acc == account) or s_pf == prop_firm:
            sheet_total = sum(
                parse_currency(str(srow.get(f'Hedge Day {d}', '')))
                for d in range(1, 35) if f'Hedge Day {d}' in df.columns
            )
            break
    
    if sheet_total is None:
        print(f"{i:<4} {prop_firm:<25} {db_total:>+12.2f} {'N/A':>12}  (no sheet match)")
    else:
        diff = db_total - sheet_total
        flag = '  ✓' if abs(diff) < 0.05 else f'  ← DIFF {diff:+.2f}'
        print(f"{i:<4} {prop_firm:<25} {db_total:>+12.2f} {sheet_total:>+12.2f}{flag}")

