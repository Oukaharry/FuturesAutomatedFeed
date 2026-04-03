#!/usr/bin/env python3
"""
Comprehensive fix for Account Number + Prop Firm across ALL clients.

Reads the push report (_log_push_report.json) to:
1. Populate missing Account Numbers from eval_account_map + session_accounts
2. Set empty Prop Firm from account prefix
3. Correct wrong Prop Firm (prefix disagrees with current firm)
4. Handle dual-account rows (challenge + funded on same row)

Usage:
    python _fix_prop_firms.py            # dry run
    python _fix_prop_firms.py --apply    # apply fixes
"""
import sqlite3, json, os, sys, shutil
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

PREFIX_TO_FIRM = {
    'FNFT': 'FundedNext',
    'MFFU': 'My Funded Futures',
    'TDF': 'TradeDay',
    'TDFY': 'Tradeify',
    'FTDF': 'Tradeify',
    'AFAD': 'Alpha Futures',
    'V2': 'Topstep',
    '50KTC': 'Topstep',
    'ELTD': 'TradeDay',
    'TDFU': 'TradeDay',
}


def derive_firm(account_number):
    """Derive firm from account number. Returns (firm, method) or (None, None)."""
    acct = account_number.strip()
    if not acct:
        return None, None

    # Method 1: Known prefix (e.g. FNFT-71643 → FundedNext)
    if '-' in acct:
        prefix = acct.rsplit('-', 1)[0].upper()
        firm = PREFIX_TO_FIRM.get(prefix)
        if firm:
            return firm, f'prefix:{prefix}'

    # Method 2: Heuristic for bare numbers
    # ≤4 digits and all numeric → Topstep (V2 accounts stored without prefix)
    if acct.isdigit() and len(acct) <= 4:
        return 'Topstep', 'heuristic:≤4digits'

    # Starts with letter (M2247, R3866, K7732, etc.) → FundedNext
    if acct and acct[0].isalpha():
        return 'FundedNext', 'heuristic:letter-start'

    return None, None


def resolve_account(partial, session_accts):
    """Resolve a partial account number to full form via session_accounts."""
    if not partial:
        return partial
    for sa in session_accts:
        if partial in sa:
            return sa
    return partial


def main():
    apply = '--apply' in sys.argv

    # ── Load push report ──
    report = {}
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        print(f"Loaded push report: {len(report.get('clients', {}))} clients")
    else:
        print(f"No push report at {REPORT_PATH} — will fix firms from existing Account Numbers only")

    # ── Load DB ──
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT client_id, evaluations FROM clients_data').fetchall()

    all_fixes = []       # (client_id, idx, field, old_val, new_val, reason)
    unmappable = []
    already_correct = 0
    no_data = 0

    for row in rows:
        client_id = row['client_id']
        evals = json.loads(row['evaluations'] or '[]')
        client_report = report.get('clients', {}).get(client_id, {})

        # Get session accounts and eval_account_map from report
        session_accts = client_report.get('session_accounts', [])
        eval_map = client_report.get('eval_account_map', {})

        # Build suffix → full session account lookup
        suffix_to_full = {}
        for full_acct in session_accts:
            if '-' in full_acct:
                suffix = full_acct.rsplit('-', 1)[1]
                suffix_to_full.setdefault(suffix, full_acct)

        for idx, ev in enumerate(evals):
            if ev.get('_deleted'):
                continue

            current_acct = ev.get('Account Number', '').strip()
            current_firm = ev.get('Prop Firm', '').strip()

            # ── Step 1: Try to populate Account Number from report data ──
            new_acct = None
            if not current_acct:
                map_entry = eval_map.get(str(idx))
                if map_entry:
                    # Handle both old format (single dict) and new format (list of dicts)
                    matches = map_entry if isinstance(map_entry, list) else [map_entry]
                    best = None
                    for m in matches:
                        if isinstance(m, dict):
                            partial = str(m.get('account', ''))
                        else:
                            partial = str(m)
                        full = resolve_account(partial, session_accts)
                        if best is None or len(full) > len(best):
                            best = full
                    if best:
                        new_acct = best
                        all_fixes.append((client_id, idx, 'Account Number', current_acct, new_acct,
                                          f'from eval_account_map'))
                        current_acct = new_acct  # use for firm derivation below

            # ── Step 2: Derive correct firm ──
            acct_for_firm = current_acct
            if not acct_for_firm:
                if not current_firm:
                    no_data += 1
                continue

            derived_firm, method = derive_firm(acct_for_firm)

            if derived_firm is None:
                if not current_firm:
                    unmappable.append((client_id, idx, acct_for_firm))
                else:
                    already_correct += 1  # has firm, can't verify but leave it
                continue

            if current_firm == derived_firm:
                already_correct += 1
                continue

            # Firm is either empty or wrong
            all_fixes.append((client_id, idx, 'Prop Firm', current_firm, derived_firm,
                              f'{method} from {acct_for_firm}'))

    # ── Report ──
    acct_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account Number']
    firm_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Prop Firm']
    empty_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if not o]
    wrong_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if o]

    print(f"\nScanned {len(rows)} clients")
    print(f"  Already correct: {already_correct}")
    print(f"  No data at all (no acct, no firm, no report entry): {no_data}")
    print(f"  Unmappable (bare >4-digit numbers): {len(unmappable)}")
    print(f"\n  Fixes needed:")
    print(f"    Account Numbers to set: {len(acct_fixes)}")
    print(f"    Empty Prop Firm → set: {len(empty_firm)}")
    print(f"    Wrong Prop Firm → correct: {len(wrong_firm)}")
    print(f"    TOTAL: {len(all_fixes)}")

    if acct_fixes:
        by_client = defaultdict(list)
        for c, i, f, o, n, r in acct_fixes:
            by_client[c].append((i, n, r))
        print(f"\n  ── Account Number fills ({len(acct_fixes)} rows across {len(by_client)} clients) ──")
        for cid in sorted(by_client.keys()):
            fixes = by_client[cid]
            print(f"    {cid}: {len(fixes)} rows")
            for idx, new_val, reason in fixes[:5]:
                print(f"      row {idx}: → {new_val}  ({reason})")
            if len(fixes) > 5:
                print(f"      ... and {len(fixes) - 5} more")

    if wrong_firm:
        print(f"\n  ── Wrong Prop Firm corrections ({len(wrong_firm)}) ──")
        for c, i, f, old, new, reason in wrong_firm:
            print(f"    {c} row {i}: {old} → {new}  ({reason})")

    if empty_firm:
        by_client = defaultdict(list)
        for c, i, f, o, n, r in empty_firm:
            by_client[c].append((i, n, r))
        print(f"\n  ── Empty Prop Firm fills ({len(empty_firm)} rows across {len(by_client)} clients) ──")
        for cid in sorted(by_client.keys()):
            fixes = by_client[cid]
            print(f"    {cid}: {len(fixes)} rows")
            for idx, new_val, reason in fixes[:5]:
                print(f"      row {idx}: → {new_val}  ({reason})")
            if len(fixes) > 5:
                print(f"      ... and {len(fixes) - 5} more")

    if unmappable:
        by_client = defaultdict(list)
        for cid, idx, acct in unmappable:
            by_client[cid].append((idx, acct))
        print(f"\n  ── Unmappable accounts — left for later ({len(unmappable)} rows) ──")
        for cid in sorted(by_client.keys()):
            items = by_client[cid]
            print(f"    {cid}: {', '.join(f'row {i} ({a})' for i, a in items[:10])}")
            if len(items) > 10:
                print(f"      ... and {len(items) - 10} more")

    if not all_fixes:
        print("\nNothing to fix.")
        conn.close()
        return

    if not apply:
        print(f"\nDRY RUN — would fix {len(all_fixes)} fields. Run with --apply to apply.")
        conn.close()
        return

    # ── Backup ──
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = DB_PATH + f'.pre_firmfix_{ts}'
    shutil.copy2(DB_PATH, backup)
    print(f"\n  Backup: {backup}")

    # ── Apply ──
    fixes_by_client = defaultdict(list)
    for c, idx, field, old, new, reason in all_fixes:
        fixes_by_client[c].append((idx, field, new))

    updated = 0
    errors = 0
    for client_id, fixes in fixes_by_client.items():
        try:
            r = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (client_id,)
            ).fetchone()
            if not r:
                errors += 1
                continue

            evals = json.loads(r['evaluations'] or '[]')
            changed = False
            for idx, field, new_val in fixes:
                if idx < len(evals):
                    evals[idx][field] = new_val
                    changed = True

            if changed:
                conn.execute(
                    'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
                    (json.dumps(evals), client_id)
                )
                updated += 1
        except Exception as e:
            print(f"  ❌ Error updating {client_id}: {e}")
            errors += 1

    conn.commit()
    conn.close()
    print(f"\n  ✅ Applied: {updated} clients updated, {errors} errors")


if __name__ == '__main__':
    main()
