#!/usr/bin/env python3
"""
Fix Prop Firm assignments across ALL clients.

1. If Account Number has a recognized prefix (FNFT-, TDF-, etc.), derive firm
2. If Prop Firm is empty → set it
3. If Prop Firm is wrong (doesn't match prefix) → correct it
4. For bare numbers: ≤4 digits → Topstep, starts with letter → FundedNext

Usage:
    python _fix_prop_firms.py            # dry run
    python _fix_prop_firms.py --apply    # apply fixes
"""
import sqlite3, json, os, sys, shutil
from datetime import datetime

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')

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

# Reverse map: firm name → set of prefixes (for validation)
FIRM_TO_PREFIXES = {}
for pfx, firm in PREFIX_TO_FIRM.items():
    FIRM_TO_PREFIXES.setdefault(firm, set()).add(pfx)


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


def main():
    apply = '--apply' in sys.argv

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT client_id, evaluations FROM clients_data').fetchall()

    all_fixes = []       # (client_id, idx, old_firm, new_firm, account, method)
    unmappable = []      # (client_id, idx, account) — can't determine firm
    already_correct = 0
    no_account = 0

    for row in rows:
        client_id = row['client_id']
        evals = json.loads(row['evaluations'] or '[]')

        for idx, ev in enumerate(evals):
            if ev.get('_deleted'):
                continue

            acct = ev.get('Account Number', '').strip()
            current_firm = ev.get('Prop Firm', '').strip()

            if not acct:
                if not current_firm:
                    no_account += 1
                continue

            derived_firm, method = derive_firm(acct)

            if derived_firm is None:
                if not current_firm:
                    unmappable.append((client_id, idx, acct))
                continue

            if current_firm == derived_firm:
                already_correct += 1
                continue

            # Firm is either empty or wrong — fix it
            all_fixes.append((client_id, idx, current_firm, derived_firm, acct, method))

    # ── Report ──
    print(f"Scanned {len(rows)} clients")
    print(f"  Already correct: {already_correct}")
    print(f"  No account at all: {no_account}")
    print(f"  Unmappable (no prefix, >4 digits, no letter start): {len(unmappable)}")
    print(f"  Fixes needed: {len(all_fixes)}")

    # Break down fixes
    empty_fixes = [(c, i, of, nf, a, m) for c, i, of, nf, a, m in all_fixes if not of]
    wrong_fixes = [(c, i, of, nf, a, m) for c, i, of, nf, a, m in all_fixes if of]
    print(f"    Empty Prop Firm → set: {len(empty_fixes)}")
    print(f"    Wrong Prop Firm → correct: {len(wrong_fixes)}")

    if wrong_fixes:
        print(f"\n  ── Wrong Prop Firm corrections ──")
        for client_id, idx, old_firm, new_firm, acct, method in wrong_fixes:
            print(f"    {client_id} row {idx}: {old_firm} → {new_firm}  (account={acct}, {method})")

    if empty_fixes:
        # Group by client
        from collections import defaultdict
        by_client = defaultdict(list)
        for client_id, idx, old_firm, new_firm, acct, method in empty_fixes:
            by_client[client_id].append((idx, new_firm, acct, method))
        print(f"\n  ── Empty Prop Firm fills ({len(empty_fixes)} rows across {len(by_client)} clients) ──")
        for cid in sorted(by_client.keys()):
            fixes = by_client[cid]
            print(f"    {cid}: {len(fixes)} rows")
            for idx, new_firm, acct, method in fixes[:5]:
                print(f"      row {idx}: → {new_firm}  (account={acct}, {method})")
            if len(fixes) > 5:
                print(f"      ... and {len(fixes) - 5} more")

    if unmappable:
        from collections import defaultdict
        by_client = defaultdict(list)
        for cid, idx, acct in unmappable:
            by_client[cid].append((idx, acct))
        print(f"\n  ── Unmappable accounts ({len(unmappable)} rows across {len(by_client)} clients) ──")
        for cid in sorted(by_client.keys()):
            items = by_client[cid]
            print(f"    {cid}: {', '.join(f'row {i} ({a})' for i, a in items)}")

    if not all_fixes:
        print("\nNothing to fix.")
        conn.close()
        return

    if not apply:
        print(f"\nDRY RUN — would fix {len(all_fixes)} rows. Run with --apply to apply.")
        conn.close()
        return

    # ── Backup ──
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = DB_PATH + f'.pre_firmfix_{ts}'
    shutil.copy2(DB_PATH, backup)
    print(f"\n  Backup: {backup}")

    # ── Apply ──
    from collections import defaultdict
    fixes_by_client = defaultdict(list)
    for client_id, idx, old_firm, new_firm, acct, method in all_fixes:
        fixes_by_client[client_id].append((idx, new_firm))

    updated = 0
    errors = 0
    for client_id, fixes in fixes_by_client.items():
        try:
            row = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (client_id,)
            ).fetchone()
            if not row:
                errors += 1
                continue

            evals = json.loads(row['evaluations'] or '[]')
            changed = False
            for idx, new_firm in fixes:
                if idx < len(evals):
                    evals[idx]['Prop Firm'] = new_firm
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
