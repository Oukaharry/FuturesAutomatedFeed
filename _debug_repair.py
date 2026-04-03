#!/usr/bin/env python3
"""Debug: show exactly what data the JSON report has for repair."""
import json, os, sqlite3

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

report = json.load(open(REPORT_PATH))
conn = sqlite3.connect(DB_PATH)

# Pick a few clients with known empty rows
test_clients = ['Alex Mosart', 'Chris Ream']

for cid in test_clients:
    print(f"\n{'='*80}")
    print(f"CLIENT: {cid}")
    print(f"{'='*80}")

    cd = report.get('clients', {}).get(cid)
    if not cd:
        print("  NOT IN JSON REPORT")
        continue

    # Session accounts
    sa = cd.get('session_accounts', [])
    print(f"\n  session_accounts ({len(sa)}):")
    for a in sa[:20]:
        print(f"    {a}")

    # Eval account map
    eam = cd.get('eval_account_map', {})
    print(f"\n  eval_account_map ({len(eam)} entries):")
    for k, v in sorted(eam.items(), key=lambda x: int(x[0])):
        print(f"    row {k}: {v}")

    # Firms
    firms = cd.get('firms', {})
    print(f"\n  firms ({len(firms)} entries):")
    for k, v in firms.items():
        print(f"    {k}: {v}")

    # Pushes summary
    pushes = cd.get('pushes', [])
    print(f"\n  pushes ({len(pushes)}):")
    for i, p in enumerate(pushes[-5:]):
        print(f"    push {len(pushes)-5+i}: eval_count={p.get('eval_count')} "
              f"hedge_writes={p.get('hedge_writes')} ts={p.get('timestamp','?')[:19]}")

    # DB state
    row = conn.execute(
        'SELECT evaluations FROM clients_data WHERE client_id = ?', (cid,)
    ).fetchone()
    if row:
        evals = json.loads(row[0] or '[]')
        print(f"\n  DB evals: {len(evals)} rows")
        # Show last 10 rows
        for i in range(max(0, len(evals)-10), len(evals)):
            e = evals[i]
            acct = e.get('Account Number', '')
            firm = e.get('Prop Firm', '')
            hr1 = e.get('Hedge Result 1', '')
            print(f"    [{i}] Acct='{acct}' Firm='{firm}' HR1='{hr1}'")
    else:
        print("  NOT IN DB")

    # Check suffix mapping
    suffix_to_full = {}
    for full_acct in sa:
        if '-' in full_acct:
            suffix = full_acct.rsplit('-', 1)[1]
            suffix_to_full.setdefault(suffix, full_acct)
    print(f"\n  suffix_to_full ({len(suffix_to_full)}):")
    for s, f in sorted(suffix_to_full.items()):
        print(f"    '{s}' -> '{f}'")

    # Try matching eval_account_map to suffixes
    print(f"\n  MATCHING eval_account_map to session_accounts:")
    for k, v in sorted(eam.items(), key=lambda x: int(x[0])):
        if isinstance(v, dict):
            partial = str(v.get('account', ''))
        else:
            partial = str(v)
        matched = suffix_to_full.get(partial, 'NO MATCH')
        print(f"    row {k}: partial='{partial}' -> {matched}")

conn.close()
print("\nDone.")
