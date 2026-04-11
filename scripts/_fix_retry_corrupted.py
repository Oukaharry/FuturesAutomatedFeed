#!/usr/bin/env python3
"""
Retry fix for clients that failed due to DB corruption.

Strategy: dump the row to JSON via a read connection (with recovery pragmas),
then write it back via a separate connection with WAL mode disabled.

Usage:
    python _fix_retry_corrupted.py            # dry run
    python _fix_retry_corrupted.py --apply    # apply
"""
import sqlite3, json, os, sys

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

FAILED_CLIENTS = [
    'Conner', 'Kelly Ream', 'Daniel P',
    'Anthony Arnold', 'Jeffrey Hinds', 'Pierre Alexandre',
]

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


def derive_firm(acct):
    acct = acct.strip()
    if not acct:
        return None
    if '-' in acct:
        prefix = acct.rsplit('-', 1)[0].upper()
        firm = PREFIX_TO_FIRM.get(prefix)
        if firm:
            return firm
    if acct.isdigit() and len(acct) <= 4:
        return 'Topstep'
    if acct and acct[0].isalpha():
        return 'FundedNext'
    return None


def resolve_account(partial, session_accts):
    if not partial:
        return partial
    for sa in session_accts:
        if partial in sa:
            return sa
    return partial


def try_read(client_id):
    """Try multiple strategies to read a client's evaluations."""
    strategies = [
        # Strategy 1: Normal read
        {},
        # Strategy 2: Writable schema + mmap off
        {'PRAGMA writable_schema = ON': None, 'PRAGMA mmap_size = 0': None},
        # Strategy 3: Journal mode OFF
        {'PRAGMA journal_mode = OFF': None, 'PRAGMA synchronous = OFF': None},
    ]
    for i, pragmas in enumerate(strategies):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.row_factory = sqlite3.Row
            for pragma in pragmas:
                conn.execute(pragma)
            row = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (client_id,)
            ).fetchone()
            conn.close()
            if row:
                return json.loads(row['evaluations'] or '[]'), i
        except Exception as e:
            try:
                conn.close()
            except:
                pass
            if i == len(strategies) - 1:
                return None, f'all strategies failed: {e}'
    return None, 'no strategies'


def try_write(client_id, evals_json):
    """Try multiple strategies to write evaluations back."""
    strategies = [
        {},
        {'PRAGMA journal_mode = OFF': None, 'PRAGMA synchronous = OFF': None},
        {'PRAGMA journal_mode = DELETE': None, 'PRAGMA synchronous = OFF': None},
    ]
    for i, pragmas in enumerate(strategies):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            for pragma in pragmas:
                conn.execute(pragma)
            conn.execute(
                'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
                (evals_json, client_id)
            )
            conn.commit()
            conn.close()
            return True, i
        except Exception as e:
            try:
                conn.close()
            except:
                pass
            if i == len(strategies) - 1:
                return False, f'all write strategies failed: {e}'
    return False, 'no strategies'


def main():
    apply = '--apply' in sys.argv

    # Load report
    report = {}
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH) as f:
            report = json.load(f)

    print(f"Retrying {len(FAILED_CLIENTS)} clients with corruption recovery...\n")

    for client_id in FAILED_CLIENTS:
        print(f"  {client_id}:")

        # Try to read
        evals, read_info = try_read(client_id)
        if evals is None:
            print(f"    ❌ Cannot read: {read_info}")
            continue
        print(f"    ✅ Read OK (strategy {read_info}), {len(evals)} evals")

        # Get report data
        client_report = report.get('clients', {}).get(client_id, {})
        session_accts = client_report.get('session_accounts', [])
        eval_map = client_report.get('eval_account_map', {})

        # Apply fixes
        changes = 0
        for idx, ev in enumerate(evals):
            if ev.get('_deleted'):
                continue

            current_acct = ev.get('Account Number', '').strip()
            current_firm = ev.get('Prop Firm', '').strip()

            # Account Number from report
            map_entry = eval_map.get(str(idx))
            if map_entry and not current_acct:
                matches = map_entry if isinstance(map_entry, list) else [map_entry]
                best = None
                for m in matches:
                    partial = str(m.get('account', '')) if isinstance(m, dict) else str(m)
                    full = resolve_account(partial, session_accts)
                    if best is None or len(full) > len(best):
                        best = full
                if best:
                    evals[idx]['Account Number'] = best
                    current_acct = best
                    changes += 1

            # Prop Firm
            if current_acct:
                derived = derive_firm(current_acct)
                if derived:
                    if not current_firm:
                        evals[idx]['Prop Firm'] = derived
                        changes += 1
                    elif current_firm != derived and '-' in current_acct:
                        # Prefix authoritative, trader may have set wrong one
                        prefix = current_acct.rsplit('-', 1)[0].upper()
                        if PREFIX_TO_FIRM.get(prefix):
                            print(f"    row {idx}: Prop Firm '{current_firm}' → '{derived}' (prefix {prefix})")
                            evals[idx]['Prop Firm'] = derived
                            changes += 1

        print(f"    {changes} fields to fix")

        if not changes:
            continue

        if not apply:
            print(f"    DRY RUN — skipping write")
            continue

        # Try to write
        ok, write_info = try_write(client_id, json.dumps(evals))
        if ok:
            print(f"    ✅ Written (strategy {write_info})")
        else:
            print(f"    ❌ Write failed: {write_info}")

    if not apply:
        print(f"\nDRY RUN. Run with --apply to apply.")


if __name__ == '__main__':
    main()
