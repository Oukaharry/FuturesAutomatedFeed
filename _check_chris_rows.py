#!/usr/bin/env python3
"""Quick lookup: show Chris Ream eval rows by display number + diagnose missing firms."""
import sqlite3, json, os

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

conn = sqlite3.connect(DB_PATH)
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris Ream'").fetchone()
conn.close()

evals = json.loads(row[0])

# Load push report for mapping data
report = {}
if os.path.exists(REPORT_PATH):
    with open(REPORT_PATH) as f:
        report = json.load(f)

chris = report.get('clients', {}).get('Chris Ream', {})
eval_map = chris.get('eval_account_map', {})
session_accts = chris.get('session_accounts', [])

# Build suffix lookup
suffix_to_full = {}
for full_acct in session_accts:
    if '-' in full_acct:
        suffix = full_acct.rsplit('-', 1)[1]
        suffix_to_full.setdefault(suffix, full_acct)

# Filter out deleted rows
visible = [(i, ev) for i, ev in enumerate(evals) if not ev.get('_deleted')]
visible.sort(key=lambda x: x[0], reverse=True)  # highest index first
total = len(visible)
display_map = {}
for i, (db_idx, ev) in enumerate(visible):
    display_num = total - i
    display_map[display_num] = (db_idx, ev)

# Show rows 620-656 (visible in screenshot + surrounds)
print(f"Chris Ream: {len(evals)} total evals, {total} visible (non-deleted)")
print(f"Session accounts: {len(session_accts)}, Eval account map entries: {len(eval_map)}")
print(f"\n{'Disp#':>5} {'DB Idx':>6}  {'Prop Firm':<20} {'Account Number':<25} {'Acct Size':<10} {'Status P1':<15} {'HedgeR1':<12} {'eval_map partial':<20} {'suffix→full'}")
print("-" * 170)
for d in range(656, 615, -1):
    if d in display_map:
        db_idx, ev = display_map[d]
        firm = ev.get('Prop Firm', '')
        acct = ev.get('Account Number', '')
        size = ev.get('Account Size', '')
        status = ev.get('Status P1', '')
        hr1 = ev.get('Hedge Result 1', '')
        # Check eval_account_map for this row
        map_entry = eval_map.get(str(db_idx), '')
        partial = ''
        if isinstance(map_entry, dict):
            partial = str(map_entry.get('account', ''))
        elif map_entry:
            partial = str(map_entry)
        # Check suffix lookup
        suffix_match = suffix_to_full.get(partial, '') if partial else ''
        marker = '  '
        if not firm:
            marker = '❌'
        print(f"{marker} {d:>3} {db_idx:>6}  {firm:<20} {acct:<25} {size:<10} {status:<15} {hr1:<12} {partial:<20} {suffix_match}")
