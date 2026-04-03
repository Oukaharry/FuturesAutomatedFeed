#!/usr/bin/env python3
"""
Comprehensive fix for Account #, Account #.1, Prop Firm, Account Size.

Reads the push report (_log_push_report.json) to:
1. Populate Account # (eval/challenge phase) and Account #.1 (funded/farming)
   using eval_account_map phase data (CH → Account #, FD/DD/FA → Account #.1)
2. Set empty Prop Firm from account prefix
3. Correct wrong Prop Firm (prefix disagrees with current firm)
4. Auto-fill Account Size for Alpha Futures ($50,000)

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
    conflicts = []       # (client_id, idx, field, existing_val, derived_val, reason)
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

            current_acct_ch = (ev.get('Account #') or '').strip()      # challenge account
            current_acct_fd = (ev.get('Account #.1') or '').strip()    # funded account
            current_firm = (ev.get('Prop Firm') or '').strip()

            # ── Step 1: Populate Account # / Account #.1 from report ──
            # eval_account_map entries have: {account, phase, num}
            # CH → Account #   |   FD/DD/FA → Account #.1
            map_entry = eval_map.get(str(idx))
            best_ch = None   # best challenge account for this row
            best_fd = None   # best funded account for this row

            if map_entry:
                matches = map_entry if isinstance(map_entry, list) else [map_entry]
                for m in matches:
                    if isinstance(m, dict):
                        partial = str(m.get('account', ''))
                        phase = str(m.get('phase', '')).upper()
                    else:
                        partial = str(m)
                        phase = ''
                    full = resolve_account(partial, session_accts)

                    if phase == 'CH':
                        if best_ch is None or len(full) > len(best_ch):
                            best_ch = full
                    elif phase in ('FD', 'DD', 'FA'):
                        if best_fd is None or len(full) > len(best_fd):
                            best_fd = full
                    else:
                        # Unknown phase — try to place in whichever field is empty
                        if not current_acct_ch and (best_ch is None or len(full) > len(best_ch)):
                            best_ch = full
                        elif not current_acct_fd and (best_fd is None or len(full) > len(best_fd)):
                            best_fd = full

            # Apply challenge account (Account #)
            if best_ch:
                if not current_acct_ch:
                    all_fixes.append((client_id, idx, 'Account #', '', best_ch,
                                      'from eval_account_map (CH)'))
                    current_acct_ch = best_ch
                elif current_acct_ch != best_ch:
                    cur_s = current_acct_ch.rsplit('-', 1)[-1] if '-' in current_acct_ch else current_acct_ch
                    der_s = best_ch.rsplit('-', 1)[-1] if '-' in best_ch else best_ch
                    if cur_s == der_s and len(best_ch) > len(current_acct_ch):
                        all_fixes.append((client_id, idx, 'Account #', current_acct_ch, best_ch,
                                          'upgrade partial→full (CH)'))
                        current_acct_ch = best_ch
                    elif cur_s != der_s:
                        conflicts.append((client_id, idx, 'Account #', current_acct_ch, best_ch,
                                          'CH mismatch'))

            # Apply funded account (Account #.1)
            if best_fd:
                if not current_acct_fd:
                    all_fixes.append((client_id, idx, 'Account #.1', '', best_fd,
                                      'from eval_account_map (FD)'))
                    current_acct_fd = best_fd
                elif current_acct_fd != best_fd:
                    cur_s = current_acct_fd.rsplit('-', 1)[-1] if '-' in current_acct_fd else current_acct_fd
                    der_s = best_fd.rsplit('-', 1)[-1] if '-' in best_fd else best_fd
                    if cur_s == der_s and len(best_fd) > len(current_acct_fd):
                        all_fixes.append((client_id, idx, 'Account #.1', current_acct_fd, best_fd,
                                          'upgrade partial→full (FD)'))
                        current_acct_fd = best_fd
                    elif cur_s != der_s:
                        conflicts.append((client_id, idx, 'Account #.1', current_acct_fd, best_fd,
                                          'FD mismatch'))

            # ── Step 2: Derive correct firm ──
            # Use whichever account is available — prefer challenge account for prefix
            acct_for_firm = current_acct_ch or current_acct_fd
            if not acct_for_firm:
                if not current_firm:
                    no_data += 1
                continue

            derived_firm, method = derive_firm(acct_for_firm)

            if derived_firm is None:
                if not current_firm:
                    unmappable.append((client_id, idx, acct_for_firm))
                else:
                    already_correct += 1
                continue

            if current_firm == derived_firm:
                already_correct += 1
                continue

            if current_firm:
                # Trader has a firm set but it disagrees with account prefix
                # Only auto-correct if prefix is definitive (not heuristic)
                if method and method.startswith('prefix:'):
                    # Prefix is authoritative — account says TDF, firm should be TradeDay
                    all_fixes.append((client_id, idx, 'Prop Firm', current_firm, derived_firm,
                                      f'corrected: {method} from {acct_for_firm}'))
                else:
                    # Heuristic — trader's manual choice is more trustworthy
                    conflicts.append((client_id, idx, 'Prop Firm', current_firm, derived_firm,
                                      f'heuristic {method} disagrees with manual'))
            else:
                # Empty firm → fill
                all_fixes.append((client_id, idx, 'Prop Firm', '', derived_firm,
                                  f'{method} from {acct_for_firm}'))

            # ── Step 3: Auto-fill Account Size for Alpha Futures ──
            effective_firm = derived_firm if derived_firm else current_firm
            current_size = (ev.get('Account Size') or '').strip()
            if effective_firm == 'Alpha Futures' and not current_size:
                all_fixes.append((client_id, idx, 'Account Size', '', '$50,000',
                                  'default for Alpha Futures'))

    # ── Report ──
    ch_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account #']
    fd_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account #.1']
    firm_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Prop Firm']
    size_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account Size']
    empty_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if not o]
    wrong_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if o]

    print(f"\nScanned {len(rows)} clients")
    print(f"  Already correct: {already_correct}")
    print(f"  No data at all (no acct, no firm, no report entry): {no_data}")
    print(f"  Unmappable (bare >4-digit numbers): {len(unmappable)}")
    print(f"  Conflicts (manual data differs — left untouched): {len(conflicts)}")
    print(f"\n  Fixes needed:")
    print(f"    Account # to set (eval/challenge): {len(ch_fixes)}")
    print(f"    Account #.1 to set (funded/farming): {len(fd_fixes)}")
    print(f"    Empty Prop Firm → set: {len(empty_firm)}")
    print(f"    Wrong Prop Firm → correct (prefix authoritative): {len(wrong_firm)}")
    print(f"    Account Size to set (Alpha Futures default): {len(size_fixes)}")
    print(f"    TOTAL: {len(all_fixes)}")

    if conflicts:
        print(f"\n  ── Conflicts (manual ≠ derived — NOT overwriting) ──")
        for c, i, f, existing, derived, reason in conflicts:
            print(f"    {c} row {i} [{f}]: has '{existing}', derived '{derived}' ({reason})")

    if ch_fixes:
        by_client = defaultdict(list)
        for c, i, f, o, n, r in ch_fixes:
            by_client[c].append((i, n, r))
        print(f"\n  ── Account # fills — eval/challenge ({len(ch_fixes)} rows across {len(by_client)} clients) ──")
        for cid in sorted(by_client.keys()):
            fixes = by_client[cid]
            print(f"    {cid}: {len(fixes)} rows")
            for idx, new_val, reason in fixes[:5]:
                print(f"      row {idx}: → {new_val}  ({reason})")
            if len(fixes) > 5:
                print(f"      ... and {len(fixes) - 5} more")

    if fd_fixes:
        by_client = defaultdict(list)
        for c, i, f, o, n, r in fd_fixes:
            by_client[c].append((i, n, r))
        print(f"\n  ── Account #.1 fills — funded/farming ({len(fd_fixes)} rows across {len(by_client)} clients) ──")
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

    # Close the read connection before apply phase
    conn.close()

    # ── Backup ──
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = DB_PATH + f'.pre_firmfix_{ts}'
    shutil.copy2(DB_PATH, backup)
    print(f"\n  Backup: {backup}")

    # ── Apply (reconnect per client to survive corrupted pages) ──
    fixes_by_client = defaultdict(list)
    for c, idx, field, old, new, reason in all_fixes:
        fixes_by_client[c].append((idx, field, new))

    updated = 0
    errors = 0
    for client_id, fixes in fixes_by_client.items():
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (client_id,)
            ).fetchone()
            if not r:
                errors += 1
                conn.close()
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
                conn.commit()
                updated += 1
            conn.close()
        except Exception as e:
            print(f"  ❌ Error updating {client_id}: {e}")
            errors += 1
            if conn:
                try:
                    conn.close()
                except:
                    pass

    print(f"\n  ✅ Applied: {updated} clients updated, {errors} errors")


if __name__ == '__main__':
    main()
