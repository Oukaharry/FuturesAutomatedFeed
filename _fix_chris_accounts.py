"""
Rebuild Chris_evaluations.csv:
1. Take FIRST 656 rows from dashboard CSV as base (has Prop Firm, Sizes, Dates, Statuses)
2. Replace corrupted account numbers (MFFUEVSTP...) with real ones from logs
3. Overlay hedge results and farming data from logs
4. Delete all rows beyond 656
"""
import csv, json, os, re

CSV_DASHBOARD = r"c:\Users\harry\Downloads\Chris_evaluations.csv"
CSV_EXTRACTED = r"_chris_ream_full.csv"
EXTRACTED_JSON = r"_chris_ream_extracted.json"
OUTPUT_PATH = r"c:\Users\harry\Downloads\Chris_evaluations_fixed.csv"

# ── Load data ──
with open(CSV_DASHBOARD, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    dash_cols = reader.fieldnames
    dash_rows = list(reader)

with open(CSV_EXTRACTED, encoding='utf-8-sig') as f:
    ext_rows = list(csv.DictReader(f))

with open(EXTRACTED_JSON) as f:
    jdata = json.load(f)

target_count = jdata['latest_eval_count']  # 656
print(f"Dashboard rows: {len(dash_rows)}")
print(f"Extracted rows: {len(ext_rows)}")
print(f"Target rows:    {target_count}")

# ── Step 1: Take first 656 dashboard rows as base ──
evaluations = []
for i in range(target_count):
    if i < len(dash_rows):
        evaluations.append(dict(dash_rows[i]))
    else:
        evaluations.append({})
print(f"\nBase: {len(evaluations)} rows from dashboard")

# ── Detect corrupted auto-generated account numbers ──
# These follow patterns like MFFUEVSTP372280001, MFFUEVSCL372280017, MFFUSFSCL372280018
CORRUPTED_PATTERN = re.compile(r'^MFFU(EVSTP|EVSCL|SFSCL)\d{9,}$')

def is_corrupted(val):
    return bool(val and CORRUPTED_PATTERN.match(val.strip()))

corrupted_a = sum(1 for ev in evaluations if is_corrupted(ev.get('Account #', '')))
corrupted_a1 = sum(1 for ev in evaluations if is_corrupted(ev.get('Account #.1', '')))
print(f"Corrupted Account #:   {corrupted_a}")
print(f"Corrupted Account #.1: {corrupted_a1}")

# ── Clear corrupted account numbers ──
for ev in evaluations:
    if is_corrupted(ev.get('Account #', '')):
        ev['Account #'] = ''
    if is_corrupted(ev.get('Account #.1', '')):
        ev['Account #.1'] = ''

# ── Build account resolution lookup ──
session_accts = jdata['session_accounts']
partial_to_full = {}
for full_acct in session_accts:
    partial_to_full[full_acct] = full_acct
    if '-' in full_acct:
        partial = full_acct.rsplit('-', 1)[-1]
        if partial not in partial_to_full:
            partial_to_full[partial] = full_acct

def resolve_account(partial):
    if not partial:
        return ''
    full = partial_to_full.get(partial)
    if full and '-' in full:
        return full
    for sa in session_accts:
        if '-' in sa and sa.endswith('-' + partial):
            return sa
    if '-' in partial:
        return partial
    return partial

# ── Firm mappings ──
FIRM_TO_PREFIX = {
    'My Funded Futures': 'MFFU', 'Tradeify': 'TDFY', 'Topstep': 'V2',
    'TradeDay': 'TDF', 'FundedNext': 'FNFT', 'Apex Trader Funding': 'APEX',
    'BluSky': 'BLSKY', 'TheFundedTrader': 'TFT', 'Alpha Futures': 'AFAD',
    'Bulenox': 'BLX', 'FastTrackTrading': 'FTT', 'TickTickTrader': 'TTT',
    'Earn2Trade': 'E2T', 'Maverick Trading': 'MAV', 'Elite Trader Funding': 'ETF',
    'Leeloo Trading': 'LELO',
}
PREFIX_TO_FIRM = {v: k for k, v in FIRM_TO_PREFIX.items()}

# ── Step 2: Apply account_maps from logs (ALL entries per row) ──
am = jdata['account_maps']
acct_placed = 0

for row_str, entries in am.items():
    row_idx = int(row_str)
    if row_idx >= target_count:
        continue
    ev = evaluations[row_idx]

    for entry in entries:
        partial = entry['account']
        phase = entry['phase'].upper()
        full_acct = resolve_account(partial)

        if phase.startswith('CH'):
            field = 'Account #'
        elif phase in ('FA', 'FD', 'DD'):
            field = 'Account #.1'
        else:
            field = 'Account #'

        existing = (ev.get(field) or '').strip()
        if not existing or ('-' not in existing and '-' in full_acct):
            ev[field] = full_acct
            acct_placed += 1

print(f"\nAccount numbers placed from logs: {acct_placed}")

# ── Step 3: Also overlay extracted CSV data where it has values ──
# The extracted CSV has Prop Firm, hedge results, farming data from log parsing
overlay_count = 0
OVERLAY_FIELDS = [
    'Prop Firm', 'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
    'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
    'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6',
    'Hedge Result 7', 'Hedge Net.1',
]
# Add Prop Day and Prop Progress columns
for d in range(1, 35):
    OVERLAY_FIELDS.append(f'Prop Day {d}')
    OVERLAY_FIELDS.append(f'Prop Progress {d}')
# Add Hedge Day columns
for d in range(1, 35):
    OVERLAY_FIELDS.append(f'Hedge Day {d}')

for i in range(min(target_count, len(ext_rows))):
    ext = ext_rows[i]
    ev = evaluations[i]
    for field in OVERLAY_FIELDS:
        ext_val = (ext.get(field) or '').strip()
        if ext_val:
            existing = (ev.get(field) or '').strip()
            if not existing:
                ev[field] = ext_val
                overlay_count += 1

print(f"Fields overlaid from extracted CSV: {overlay_count}")

# ── Step 4: Apply hedge_writes directly ──
hw = jdata['hedge_writes']
hw_applied = 0
for h in hw:
    row_idx = h['row']
    col = h['col']
    val = h['val']
    if row_idx < target_count:
        evaluations[row_idx][col] = str(val)
        hw_applied += 1
print(f"Hedge writes applied: {hw_applied}")

# ── Step 5: Apply farming_writes ──
fw = jdata['farming_writes']
fw_applied = 0
for f_entry in fw:
    row_idx = f_entry['row']
    day = f_entry['day']
    val = f_entry['val']
    if row_idx < target_count:
        col_name = f'Prop Day {day}'
        evaluations[row_idx][col_name] = str(val)
        fw_applied += 1
print(f"Farming writes applied: {fw_applied}")

# ── Step 6: Derive Prop Firm from account where dashboard had wrong firm or empty ──
firm_derived = 0
for ev in evaluations:
    if (ev.get('Prop Firm') or '').strip():
        continue
    for field in ('Account #', 'Account #.1'):
        acct = (ev.get(field) or '').strip()
        if acct and '-' in acct:
            prefix = acct.split('-')[0]
            firm = PREFIX_TO_FIRM.get(prefix)
            if firm:
                ev['Prop Firm'] = firm
                firm_derived += 1
                break
print(f"Prop Firm derived from accounts: {firm_derived}")

# ── Fix partial account numbers ──
partial_fixed = 0
for ev in evaluations:
    for field in ('Account #', 'Account #.1'):
        val = (ev.get(field) or '').strip()
        if val and '-' not in val and not is_corrupted(val):
            firm = (ev.get('Prop Firm') or '').strip()
            prefix = FIRM_TO_PREFIX.get(firm)
            if prefix:
                ev[field] = f"{prefix}-{val}"
                partial_fixed += 1
print(f"Partial accounts fixed: {partial_fixed}")

# ── Assign Row # ──
for i, ev in enumerate(evaluations):
    ev['Row #'] = str(i)

# ── Final statistics ──
has_a = sum(1 for ev in evaluations if (ev.get('Account #') or '').strip())
has_a1 = sum(1 for ev in evaluations if (ev.get('Account #.1') or '').strip())
has_either = sum(1 for ev in evaluations
                 if (ev.get('Account #') or '').strip() or (ev.get('Account #.1') or '').strip())
miss_both = target_count - has_either
has_firm = sum(1 for ev in evaluations if (ev.get('Prop Firm') or '').strip())

print(f"\n{'='*60}")
print(f"FINAL COVERAGE ({target_count} rows):")
print(f"  Account #:     {has_a:4d} ({has_a*100//target_count}%)")
print(f"  Account #.1:   {has_a1:4d} ({has_a1*100//target_count}%)")
print(f"  Has either:    {has_either:4d} ({has_either*100//target_count}%)")
print(f"  Missing BOTH:  {miss_both:4d} ({miss_both*100//target_count}%)")
print(f"  Prop Firm:     {has_firm:4d} ({has_firm*100//target_count}%)")
print(f"{'='*60}")

# Show some still-missing rows
missing = [i for i, ev in enumerate(evaluations)
           if not (ev.get('Account #') or '').strip() and not (ev.get('Account #.1') or '').strip()]
if missing:
    print(f"\nRows with no account (sample of first 20):")
    for i in missing[:20]:
        ev = evaluations[i]
        pf = (ev.get('Prop Firm') or '(none)').strip()
        sz = (ev.get('Account Size') or '').strip()
        dp = (ev.get('Date Purchased') or '').strip()
        s1 = (ev.get('Status P1') or '').strip()
        print(f"  Row {i:3d}: {pf:20s} {sz:10s} Date={dp:12s} StatusP1={s1}")

# ── Write output ──
output_cols = list(dash_cols)
with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=output_cols, extrasaction='ignore')
    writer.writeheader()
    for ev in evaluations:
        row = {col: (ev.get(col) or '') for col in output_cols}
        writer.writerow(row)

print(f"\nWrote {len(evaluations)} rows x {len(output_cols)} cols to:")
print(f"  {OUTPUT_PATH}")
print(f"  (deleted {len(dash_rows) - target_count} excess rows from original {len(dash_rows)})")
