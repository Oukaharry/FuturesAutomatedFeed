#!/usr/bin/env python3
"""
Debug: Check Chris Ream's eval_account_map in the push report
and show which rows have Account Number populated vs empty.
Also check BEF payout impact from Prop Firm corrections.
"""
import sqlite3, json, os

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

BEF_HIDDEN_FIRMS = {'lucid', 'apex', 'tradeday', 'toponefutures'}

# ── Part 1: Chris Ream account number debug ──
print("=" * 80)
print("PART 1: Chris Ream Account Number Debug")
print("=" * 80)

report = {}
if os.path.exists(REPORT_PATH):
    with open(REPORT_PATH) as f:
        report = json.load(f)

chris = report.get('clients', {}).get('Chris Ream', {})
eval_map = chris.get('eval_account_map', {})
session_accts = chris.get('session_accounts', [])

print(f"Report has {len(eval_map)} eval_account_map entries for Chris Ream")
print(f"Session accounts: {len(session_accts)}")

# Show first 10 entries to see the format
print("\nSample eval_account_map entries:")
for k in sorted(eval_map.keys(), key=lambda x: int(x))[:10]:
    v = eval_map[k]
    print(f"  idx {k}: {v}  (type={type(v).__name__})")

# Now load DB and check
conn = sqlite3.connect(DB_PATH)
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris Ream'").fetchone()
evals = json.loads(row[0]) if row else []

# Count empties at the top (highest indices = newest = displayed at top)
empty_acct_rows = []
filled_acct_rows = []
for idx, ev in enumerate(evals):
    if ev.get('_deleted'):
        continue
    acct = ev.get('Account Number', '').strip()
    if not acct:
        has_map = str(idx) in eval_map
        hr1 = ev.get('Hedge Result 1', '')
        empty_acct_rows.append((idx, has_map, hr1))
    else:
        filled_acct_rows.append(idx)

print(f"\nDB: {len(evals)} total evals, {len(empty_acct_rows)} with empty Account Number (non-deleted)")
print(f"    {len(filled_acct_rows)} have Account Numbers filled")

# Show empty rows that DO have eval_map entries (should have been filled)
missed = [(idx, has_map, hr1) for idx, has_map, hr1 in empty_acct_rows if has_map]
print(f"\nEmpty Account # rows that HAVE eval_map entries (should have been filled): {len(missed)}")
for idx, _, hr1 in missed[:20]:
    entry = eval_map[str(idx)]
    print(f"  row {idx}: map={entry}, HR1={hr1}")

# Show empty rows that DON'T have eval_map entries
no_map = [(idx, has_map, hr1) for idx, has_map, hr1 in empty_acct_rows if not has_map]
print(f"\nEmpty Account # rows with NO eval_map entry: {len(no_map)}")
for idx, _, hr1 in no_map[:20]:
    print(f"  row {idx}: HR1={hr1}")
if len(no_map) > 20:
    print(f"  ... and {len(no_map) - 20} more")

# ── Part 2: BEF Payout Impact ──
print("\n" + "=" * 80)
print("PART 2: BEF Payout Impact from Prop Firm Corrections")
print("=" * 80)

# Check ALL clients: find rows where Prop Firm is now in BEF_HIDDEN_FIRMS
# and has payouts
rows = conn.execute('SELECT client_id, evaluations FROM clients_data').fetchall()
conn.close()

hidden_payout_total = 0
hidden_rows = []

for r in rows:
    client_id = r[0]
    evals = json.loads(r[1] or '[]')
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        firm = str(ev.get('Prop Firm', '')).strip()
        if firm.lower().replace(' ', '') not in BEF_HIDDEN_FIRMS:
            continue
        # This row IS hidden from BEF — check if it has payouts
        row_payouts = 0
        for i in range(1, 10):
            pval = ev.get(f'Payout {i}', '')
            if pval:
                try:
                    cleaned = str(pval).replace('$', '').replace(',', '').strip()
                    if cleaned:
                        row_payouts += float(cleaned)
                except:
                    pass
        if row_payouts > 0:
            hidden_payout_total += row_payouts
            hidden_rows.append((client_id, idx, firm, row_payouts))

print(f"Total payouts on BEF-hidden firms: ${hidden_payout_total:,.2f}")
print(f"Across {len(hidden_rows)} eval rows")

# Group by firm
from collections import defaultdict
by_firm = defaultdict(float)
by_firm_count = defaultdict(int)
for cid, idx, firm, pay in hidden_rows:
    by_firm[firm] += pay
    by_firm_count[firm] += 1

print("\nBreakdown by firm:")
for firm in sorted(by_firm.keys()):
    print(f"  {firm}: ${by_firm[firm]:,.2f} across {by_firm_count[firm]} rows")

# Show top 10 biggest hidden payout rows
print("\nTop 20 hidden payout rows:")
hidden_rows.sort(key=lambda x: x[3], reverse=True)
for cid, idx, firm, pay in hidden_rows[:20]:
    print(f"  {cid} row {idx}: {firm} → ${pay:,.2f}")
