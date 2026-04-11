#!/usr/bin/env python3
"""
Targeted fix for Chris Ream's account numbers only.

Rules:
1. Pre-existing MT5 account strings (long format like MFFUEVSTP..., FTPROPLUS...) → LEAVE ALONE
2. Values in session_accounts → VALID, keep
3. Short values NOT in session_accounts (our bad placements) → CLEAR
4. Re-apply eval_account_map entries that resolve to real session accounts
5. CH phase → Account #, FA/FD/DD phase → Account #.1

Usage:
    python3 _fix_chris_ream.py                # dry run
    python3 _fix_chris_ream.py --apply        # apply
"""
import sqlite3, json, os, sys
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')
CLIENT_ID = 'Chris Ream'

# Prefixes that indicate a pre-existing MT5 account string (NOT from our scripts)
PRE_EXISTING_PREFIXES = (
    'MFFUEVSTP', 'MFFUEVSCL', 'MFFUSFSCL', 'MFFUSFSTP',
    'FTPROPLUS', 'FTPROPLUSM',
    'ELTDEN', 'ELTDFD',
    'TDFYSL', 'TDFYFD',
    'FTDFSL', 'FTDFFD',
)


def is_pre_existing(acct):
    """Check if this is a pre-existing MT5 account string (not placed by us)."""
    if not acct:
        return False
    upper = acct.upper()
    for prefix in PRE_EXISTING_PREFIXES:
        if upper.startswith(prefix) and len(acct) > 12:
            return True
    return False


def resolve_to_session(partial, session_accts, suffix_to_full):
    """
    Resolve a partial account to a VALIDATED session account.
    Returns (full_account, method) or (None, reason).
    """
    if not partial:
        return None, 'empty'

    # Direct match
    for sa in session_accts:
        if partial == sa:
            return sa, 'exact'

    # Suffix match: partial is the suffix after hyphen
    if partial in suffix_to_full:
        full = suffix_to_full[partial]
        return full, f'suffix→{full}'

    # Substring match (partial appears somewhere in a session account)
    matches = [sa for sa in session_accts if partial in sa]
    if len(matches) == 1:
        return matches[0], f'substring→{matches[0]}'
    elif len(matches) > 1:
        # Ambiguous — try suffix match more carefully
        suffix_matches = [m for m in matches if m.endswith(partial) or m.endswith('-' + partial)]
        if len(suffix_matches) == 1:
            return suffix_matches[0], f'suffix-disambig→{suffix_matches[0]}'
        return None, f'ambiguous:{",".join(sorted(matches))}'

    return None, f'not-found'


def main():
    apply = '--apply' in sys.argv

    # ── Load push report ──
    with open(REPORT_PATH) as f:
        report = json.load(f)
    client_report = report.get('clients', {}).get(CLIENT_ID, {})
    session_accts = set(client_report.get('session_accounts', []))
    eval_map = client_report.get('eval_account_map', {})

    print(f"\n{'='*70}")
    print(f"  TARGETED FIX: {CLIENT_ID}")
    print(f"{'='*70}")
    print(f"  Session accounts: {len(session_accts)}")
    print(f"  eval_account_map entries: {len(eval_map)} rows")

    # Build suffix lookup
    suffix_to_full = {}
    for sa in session_accts:
        if '-' in sa:
            suffix = sa.rsplit('-', 1)[1]
            # Only store if unique suffix
            if suffix not in suffix_to_full:
                suffix_to_full[suffix] = sa
            else:
                # Collision — mark as ambiguous
                suffix_to_full[suffix] = None

    # Remove ambiguous suffixes
    suffix_to_full = {k: v for k, v in suffix_to_full.items() if v is not None}

    # ── Load DB ──
    conn = sqlite3.connect(DB_PATH, timeout=30)
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,)
    ).fetchone()
    conn.close()
    evals = json.loads(row[0] or '[]')
    print(f"  Total rows: {len(evals)}")

    fixes = []      # (idx, field, old_val, new_val, reason)
    skipped = []    # (idx, field, val, reason)
    warnings = []   # (idx, message)

    # ── Pass 1: Clear bad placements (our values that aren't valid) ──
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue

        for field in ('Account #', 'Account #.1'):
            val = (ev.get(field) or '').strip()
            if not val:
                continue

            if val in session_accts:
                continue  # Valid — keep it

            if is_pre_existing(val):
                continue  # Pre-existing MT5 string — don't touch

            # This is a short value NOT in session_accounts — our bad placement
            fixes.append((idx, field, val, '', f'clear invalid (not in MT5): {val}'))

    # ── Pass 2: Place validated eval_account_map entries ──
    # First, figure out what each row will look like after Pass 1 clears
    projected = {}  # idx → {field: val}
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        projected[idx] = {'Account #': ch, 'Account #.1': fd}

    # Apply pass 1 clears to projection
    for idx, field, old, new, reason in fixes:
        if idx in projected:
            projected[idx][field] = new

    # Now apply map entries
    for str_idx, map_entry in eval_map.items():
        idx = int(str_idx)
        if idx not in projected:
            continue

        entries = map_entry if isinstance(map_entry, list) else [map_entry]

        # Collect validated accounts by phase
        ch_candidates = []
        fd_candidates = []

        for e in entries:
            if not isinstance(e, dict):
                continue
            partial = str(e.get('account', ''))
            phase = str(e.get('phase', '')).upper()

            full, method = resolve_to_session(partial, session_accts, suffix_to_full)
            if full is None:
                if 'not-found' in method:
                    warnings.append((idx, f'map account {partial}({phase}) not in session_accounts — skipping'))
                elif 'ambiguous' in method:
                    warnings.append((idx, f'map account {partial}({phase}) ambiguous: {method} — skipping'))
                continue

            if phase == 'CH':
                if full not in ch_candidates:
                    ch_candidates.append(full)
            elif phase in ('FD', 'DD', 'FA'):
                if full not in fd_candidates:
                    fd_candidates.append(full)
            else:
                # Unknown phase, try challenge first
                if full not in ch_candidates:
                    ch_candidates.append(full)

        # Place challenge account
        current_ch = projected[idx]['Account #']
        if ch_candidates and not current_ch:
            best_ch = ch_candidates[0]
            fixes.append((idx, 'Account #', '', best_ch, f'from map CH: {best_ch}'))
            projected[idx]['Account #'] = best_ch
        elif ch_candidates and current_ch in session_accts and current_ch not in ch_candidates:
            # Already has a valid session account that differs from map — note but don't change
            skipped.append((idx, 'Account #', current_ch, f'already valid, map suggests {ch_candidates[0]}'))

        # Place funded account
        current_fd = projected[idx]['Account #.1']
        if fd_candidates and not current_fd:
            best_fd = fd_candidates[0]
            fixes.append((idx, 'Account #.1', '', best_fd, f'from map FA/FD: {best_fd}'))
            projected[idx]['Account #.1'] = best_fd
        elif fd_candidates and current_fd in session_accts and current_fd not in fd_candidates:
            skipped.append((idx, 'Account #.1', current_fd, f'already valid, map suggests {fd_candidates[0]}'))

        # If we have funded candidates but Account #.1 has a pre-existing value,
        # and Account # is empty, DON'T put funded acct there — just skip
        # (don't cross-fill into wrong column)

    # ── Also clear remaining legacy Account Number values (after Step 0 migration) ──
    legacy_clears = 0
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        legacy = (ev.get('Account Number') or '').strip()
        if legacy:
            if legacy in session_accts:
                # Valid legacy — migrate to correct column if empty
                ch = projected.get(idx, {}).get('Account #', '')
                fd = projected.get(idx, {}).get('Account #.1', '')
                if not fd:
                    fixes.append((idx, 'Account #.1', '', legacy,
                                  f'migrate valid legacy to funded: {legacy}'))
                elif not ch:
                    fixes.append((idx, 'Account #', '', legacy,
                                  f'migrate valid legacy to challenge: {legacy}'))
            # Always remove the legacy field
            fixes.append((idx, 'Account Number', legacy, '', 'remove legacy field'))
            legacy_clears += 1

    # ── Summary ──
    clear_fixes = [f for f in fixes if f[3] == '' and f[1] != 'Account Number']
    ch_fills = [f for f in fixes if f[1] == 'Account #' and f[3] != '']
    fd_fills = [f for f in fixes if f[1] == 'Account #.1' and f[3] != '']
    legacy_rm = [f for f in fixes if f[1] == 'Account Number']

    print(f"\n  ── Results ──")
    print(f"  Invalid values to CLEAR: {len(clear_fixes)}")
    print(f"  Account # to fill (challenge): {len(ch_fills)}")
    print(f"  Account #.1 to fill (funded): {len(fd_fills)}")
    print(f"  Legacy Account Number to remove: {len(legacy_rm)}")
    print(f"  Warnings (unresolvable map entries): {len(warnings)}")
    print(f"  Skipped (already valid, different from map): {len(skipped)}")
    print(f"  TOTAL operations: {len(fixes)}")

    # ── Write detailed report ──
    rpt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_fix_chris_ream_report.txt')
    with open(rpt_path, 'w') as f:
        f.write(f"TARGETED FIX: {CLIENT_ID}\n")
        f.write(f"{'='*70}\n\n")

        if clear_fixes:
            f.write(f"── CLEARING invalid values ({len(clear_fixes)}) ──\n")
            for idx, field, old, new, reason in clear_fixes:
                f.write(f"  row {idx} [{field}]: '{old}' → '' ({reason})\n")
            f.write('\n')

        if ch_fills:
            f.write(f"── FILLING Account # ({len(ch_fills)}) ──\n")
            for idx, field, old, new, reason in ch_fills:
                f.write(f"  row {idx}: → '{new}' ({reason})\n")
            f.write('\n')

        if fd_fills:
            f.write(f"── FILLING Account #.1 ({len(fd_fills)}) ──\n")
            for idx, field, old, new, reason in fd_fills:
                f.write(f"  row {idx}: → '{new}' ({reason})\n")
            f.write('\n')

        if warnings:
            f.write(f"── WARNINGS ({len(warnings)}) ──\n")
            for idx, msg in warnings:
                f.write(f"  row {idx}: {msg}\n")
            f.write('\n')

        if skipped:
            f.write(f"── SKIPPED (already valid) ({len(skipped)}) ──\n")
            for idx, field, val, reason in skipped:
                f.write(f"  row {idx} [{field}]: '{val}' — {reason}\n")
            f.write('\n')

    print(f"\n  Full report: {rpt_path}")

    # ── Show sample of fixes ──
    print(f"\n  ── Sample fixes (first 20) ──")
    for fix in fixes[:20]:
        idx, field, old, new, reason = fix
        if new:
            print(f"    row {idx} [{field}]: '{old}' → '{new}'")
        else:
            print(f"    row {idx} [{field}]: CLEAR '{old}'")

    if not apply:
        print(f"\n  DRY RUN — run with --apply to apply {len(fixes)} changes.")
        return

    # ── Apply ──
    print(f"\n  Applying {len(fixes)} changes...", flush=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,)
    ).fetchone()
    evals = json.loads(row[0] or '[]')

    for idx, field, old, new, reason in fixes:
        if idx < len(evals):
            if field == 'Account Number' and new == '':
                if 'Account Number' in evals[idx]:
                    del evals[idx]['Account Number']
            elif new == '':
                evals[idx][field] = ''
            else:
                evals[idx][field] = new

    conn.execute(
        'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
        (json.dumps(evals), CLIENT_ID)
    )
    conn.commit()
    conn.close()
    print(f"  ✅ Done — {len(fixes)} changes applied to {CLIENT_ID}")


if __name__ == '__main__':
    main()
