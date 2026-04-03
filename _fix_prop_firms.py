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

    upper = acct.upper()

    # Method 1: Known prefix with hyphen (e.g. FNFT-71643 → FundedNext)
    if '-' in acct:
        prefix = acct.rsplit('-', 1)[0].upper()
        firm = PREFIX_TO_FIRM.get(prefix)
        if firm:
            return firm, f'prefix:{prefix}'

    # Method 2: Known prefix as start of full account string
    # e.g. TDFYSL50816736838 → Tradeify, MFFUEVFLX372280283 → My Funded Futures
    for prefix, firm in sorted(PREFIX_TO_FIRM.items(), key=lambda x: -len(x[0])):
        if upper.startswith(prefix):
            return firm, f'prefix-start:{prefix}'

    # Method 3: Bare number heuristics
    if acct.isdigit() and len(acct) <= 4:
        return 'Topstep', 'heuristic:≤4digits'

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

    # ── Load DB (per-client to survive corrupt pages) ──
    def get_all_clients():
        """Load all client data, skipping corrupt rows."""
        results = []
        c = sqlite3.connect(DB_PATH, timeout=15)
        c.execute("PRAGMA journal_mode=OFF")
        c.execute("PRAGMA ignore_check_constraints=ON")
        try:
            client_ids = [r[0] for r in c.execute('SELECT client_id FROM clients_data').fetchall()]
        except sqlite3.DatabaseError:
            # If even the ID list fails, try with integrity_check off
            c.close()
            c = sqlite3.connect(DB_PATH, timeout=15)
            c.execute("PRAGMA journal_mode=OFF")
            c.execute("PRAGMA ignore_check_constraints=ON")
            c.execute("PRAGMA writable_schema=ON")
            client_ids = [r[0] for r in c.execute('SELECT client_id FROM clients_data').fetchall()]
        c.close()
        print(f"Found {len(client_ids)} clients in DB")

        for cid in client_ids:
            try:
                c2 = sqlite3.connect(DB_PATH, timeout=15)
                c2.execute("PRAGMA journal_mode=OFF")
                row = c2.execute(
                    'SELECT client_id, evaluations FROM clients_data WHERE client_id=?', (cid,)
                ).fetchone()
                c2.close()
                if row:
                    results.append({'client_id': row[0], 'evaluations': row[1]})
            except sqlite3.DatabaseError as e:
                print(f"  ⚠ Skipping {cid}: {e}", flush=True)
        return results

    rows = get_all_clients()

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

            # ── Step 0: Migrate stale "Account Number" field into correct column ──
            # Old V2 reconstruction wrote to "Account Number" — move to Account # or #.1
            legacy_acct = (ev.get('Account Number') or '').strip()
            if legacy_acct:
                # Determine phase from eval_account_map if available
                legacy_phase = ''
                map_entry_legacy = eval_map.get(str(idx))
                if map_entry_legacy:
                    entries = map_entry_legacy if isinstance(map_entry_legacy, list) else [map_entry_legacy]
                    # Check if any entry's account matches the legacy value (substring either way)
                    for m in entries:
                        if isinstance(m, dict):
                            map_acct = str(m.get('account', ''))
                            if map_acct and (map_acct in legacy_acct or legacy_acct in map_acct
                                             or (map_acct.split('-')[-1] if '-' in map_acct else map_acct)
                                                 in legacy_acct):
                                legacy_phase = str(m.get('phase', '')).upper()
                                break
                    # If no match found, use first entry's phase
                    if not legacy_phase and entries:
                        m0 = entries[0]
                        if isinstance(m0, dict):
                            legacy_phase = str(m0.get('phase', '')).upper()

                # If still no phase, infer from which columns already have data:
                # If Account # has data but Account #.1 is empty → funded
                # If Account #.1 has data but Account # is empty → challenge
                # If both empty → check hedge results to determine phase
                if not legacy_phase:
                    has_ch_results = any(ev.get(f'Hedge Result {i}') for i in range(1, 6))
                    has_fd_results = any(ev.get(f'Hedge Result {i}.1') for i in range(1, 6))
                    has_farming = any(ev.get(f'Hedge Day {i}') for i in range(1, 11))
                    if current_acct_ch and not current_acct_fd:
                        legacy_phase = 'FD'  # ch already filled, this must be funded
                    elif current_acct_fd and not current_acct_ch:
                        legacy_phase = 'CH'  # fd already filled, this must be challenge
                    elif has_fd_results or has_farming:
                        legacy_phase = 'FD'
                    elif has_ch_results:
                        legacy_phase = 'CH'

                if legacy_phase in ('FD', 'DD', 'FA'):
                    if not current_acct_fd:
                        all_fixes.append((client_id, idx, 'Account #.1', '', legacy_acct,
                                          'migrated from Account Number (funded)'))
                        current_acct_fd = legacy_acct
                    elif not current_acct_ch:
                        # funded already filled — put in challenge instead
                        all_fixes.append((client_id, idx, 'Account #', '', legacy_acct,
                                          'migrated from Account Number (fallback to CH)'))
                        current_acct_ch = legacy_acct
                else:
                    # Default to challenge column
                    if not current_acct_ch:
                        all_fixes.append((client_id, idx, 'Account #', '', legacy_acct,
                                          'migrated from Account Number (challenge)'))
                        current_acct_ch = legacy_acct
                    elif not current_acct_fd:
                        # challenge already filled — put in funded instead
                        all_fixes.append((client_id, idx, 'Account #.1', '', legacy_acct,
                                          'migrated from Account Number (fallback to FD)'))
                        current_acct_fd = legacy_acct

                # Always remove the stale "Account Number" key
                all_fixes.append((client_id, idx, 'Account Number', legacy_acct, '',
                                  'remove legacy field'))

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

    # ── Report (write details to file, summary to console) ──
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_fix_prop_firms_report.txt')
    ch_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account #']
    fd_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account #.1']
    legacy_rm = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account Number']
    firm_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Prop Firm']
    size_fixes = [(c, i, f, o, n, r) for c, i, f, o, n, r in all_fixes if f == 'Account Size']
    empty_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if not o]
    wrong_firm = [(c, i, f, o, n, r) for c, i, f, o, n, r in firm_fixes if o]
    real_fixes = [x for x in all_fixes if x[2] != 'Account Number']  # exclude removals from count

    summary = []
    summary.append(f"\nScanned {len(rows)} clients")
    summary.append(f"  Already correct: {already_correct}")
    summary.append(f"  No data at all (no acct, no firm, no report entry): {no_data}")
    summary.append(f"  Unmappable: {len(unmappable)}")
    summary.append(f"  Conflicts (manual data differs — left untouched): {len(conflicts)}")
    summary.append(f"\n  Fixes needed:")
    summary.append(f"    Account # to set (eval/challenge): {len(ch_fixes)}")
    summary.append(f"    Account #.1 to set (funded/farming): {len(fd_fixes)}")
    summary.append(f"    Legacy 'Account Number' → migrate + remove: {len(legacy_rm)}")
    summary.append(f"    Empty Prop Firm → set: {len(empty_firm)}")
    summary.append(f"    Wrong Prop Firm → correct (prefix authoritative): {len(wrong_firm)}")
    summary.append(f"    Account Size to set (Alpha Futures default): {len(size_fixes)}")
    summary.append(f"    TOTAL (fields to update): {len(all_fixes)}")

    # Print summary to console
    for line in summary:
        print(line)

    # Write full details to file
    with open(log_path, 'w') as lf:
        for line in summary:
            lf.write(line + '\n')

        if conflicts:
            lf.write(f"\n  ── Conflicts (manual ≠ derived — NOT overwriting) ──\n")
            for c, i, f, existing, derived, reason in conflicts:
                lf.write(f"    {c} row {i} [{f}]: has '{existing}', derived '{derived}' ({reason})\n")

        if ch_fixes:
            by_client = defaultdict(list)
            for c, i, f, o, n, r in ch_fixes:
                by_client[c].append((i, n, r))
            lf.write(f"\n  ── Account # fills — eval/challenge ({len(ch_fixes)} rows across {len(by_client)} clients) ──\n")
            for cid in sorted(by_client.keys()):
                fixes = by_client[cid]
                lf.write(f"    {cid}: {len(fixes)} rows\n")
                for idx, new_val, reason in fixes:
                    lf.write(f"      row {idx}: → {new_val}  ({reason})\n")

        if fd_fixes:
            by_client = defaultdict(list)
            for c, i, f, o, n, r in fd_fixes:
                by_client[c].append((i, n, r))
            lf.write(f"\n  ── Account #.1 fills — funded/farming ({len(fd_fixes)} rows across {len(by_client)} clients) ──\n")
            for cid in sorted(by_client.keys()):
                fixes = by_client[cid]
                lf.write(f"    {cid}: {len(fixes)} rows\n")
                for idx, new_val, reason in fixes:
                    lf.write(f"      row {idx}: → {new_val}  ({reason})\n")

        if wrong_firm:
            lf.write(f"\n  ── Wrong Prop Firm corrections ({len(wrong_firm)}) ──\n")
            for c, i, f, old, new, reason in wrong_firm:
                lf.write(f"    {c} row {i}: {old} → {new}  ({reason})\n")

        if empty_firm:
            by_client = defaultdict(list)
            for c, i, f, o, n, r in empty_firm:
                by_client[c].append((i, n, r))
            lf.write(f"\n  ── Empty Prop Firm fills ({len(empty_firm)} rows across {len(by_client)} clients) ──\n")
            for cid in sorted(by_client.keys()):
                fixes = by_client[cid]
                lf.write(f"    {cid}: {len(fixes)} rows\n")
                for idx, new_val, reason in fixes:
                    lf.write(f"      row {idx}: → {new_val}  ({reason})\n")

        if unmappable:
            by_client = defaultdict(list)
            for cid, idx, acct in unmappable:
                by_client[cid].append((idx, acct))
            lf.write(f"\n  ── Unmappable accounts ({len(unmappable)} rows) ──\n")
            for cid in sorted(by_client.keys()):
                items = by_client[cid]
                lf.write(f"    {cid}: {', '.join(f'row {i} ({a})' for i, a in items)}\n")

    print(f"\n  Full report: {log_path}")

    if not all_fixes:
        print("\nNothing to fix.")
        return

    if not apply:
        print(f"\nDRY RUN — would fix {len(all_fixes)} fields. Run with --apply to apply.")
        return

    # Group fixes by client
    fixes_by_client = defaultdict(list)
    for c, idx, field, old, new, reason in all_fixes:
        fixes_by_client[c].append((idx, field, new))

    # ── Backup (skip if --no-backup to avoid hanging on large/corrupted DB) ──
    if '--no-backup' not in sys.argv:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = DB_PATH + f'.pre_firmfix_{ts}'
        print(f"\n  Creating backup... ", end='', flush=True)
        shutil.copy2(DB_PATH, backup)
        print(f"done: {backup}", flush=True)
    else:
        print(f"\n  Skipping backup (--no-backup)", flush=True)

    print(f"\n  Applying {len(all_fixes)} fixes across {len(fixes_by_client)} clients...", flush=True)

    # ── Apply (reconnect per client to survive corrupted pages) ──
    total_clients = len(fixes_by_client)
    updated = 0
    errors = 0
    skipped = 0
    for i, (client_id, fixes) in enumerate(fixes_by_client.items(), 1):
        print(f"  [{i}/{total_clients}] {client_id} ({len(fixes)} fixes)...", end=' ', flush=True)
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=15)
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (client_id,)
            ).fetchone()
            if not r:
                print("NOT FOUND")
                skipped += 1
                conn.close()
                continue

            evals = json.loads(r['evaluations'] or '[]')
            changed = False
            for idx, field, new_val in fixes:
                if idx < len(evals):
                    if field == 'Account Number' and new_val == '':
                        # Remove the legacy field entirely
                        if 'Account Number' in evals[idx]:
                            del evals[idx]['Account Number']
                            changed = True
                    else:
                        evals[idx][field] = new_val
                        changed = True

            if changed:
                conn.execute(
                    'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
                    (json.dumps(evals), client_id)
                )
                conn.commit()
                updated += 1
                print("OK")
            else:
                skipped += 1
                print("no changes")
            conn.close()
        except Exception as e:
            print(f"  ❌ Error updating {client_id}: {e}")
            errors += 1
            if conn:
                try:
                    conn.close()
                except:
                    pass

    print(f"\n  ✅ Applied: {updated} clients updated, {skipped} skipped, {errors} errors")


if __name__ == '__main__':
    main()
