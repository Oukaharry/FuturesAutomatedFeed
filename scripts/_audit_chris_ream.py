#!/usr/bin/env python3
"""
Deep audit of Chris Ream's account numbers.

Cross-references:
1. Current DB values (Account #, Account #.1) against session_accounts
2. eval_account_map entries — what was reconstructed from logs
3. Flags accounts NOT in session_accounts (invalid/wrong client)
4. Flags partial accounts that weren't resolved
5. Shows rows where Account # should be Account #.1 or vice versa

Usage:
    python3 _audit_chris_ream.py
"""
import sqlite3, json, os, sys
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')

PREFIX_TO_FIRM = {
    'FNFT': 'FundedNext', 'MFFU': 'My Funded Futures', 'TDF': 'TradeDay',
    'TDFY': 'Tradeify', 'FTDF': 'Tradeify', 'AFAD': 'Alpha Futures',
    'V2': 'Topstep', '50KTC': 'Topstep', 'ELTD': 'TradeDay', 'TDFU': 'TradeDay',
}

CLIENT_ID = 'Chris Ream'


def main():
    # ── Load push report ──
    with open(REPORT_PATH) as f:
        report = json.load(f)
    client_report = report.get('clients', {}).get(CLIENT_ID, {})
    session_accts = set(client_report.get('session_accounts', []))
    eval_map = client_report.get('eval_account_map', {})

    print(f"\n{'='*80}")
    print(f"  DEEP AUDIT: {CLIENT_ID}")
    print(f"{'='*80}")
    print(f"  Session accounts (real MT5): {len(session_accts)}")

    # Build suffix lookup: suffix → full account
    suffix_to_full = {}
    suffix_collisions = {}
    for sa in session_accts:
        if '-' in sa:
            suffix = sa.rsplit('-', 1)[1]
            if suffix in suffix_to_full:
                suffix_collisions.setdefault(suffix, [suffix_to_full[suffix]]).append(sa)
            else:
                suffix_to_full[suffix] = sa

    if suffix_collisions:
        print(f"\n  ⚠ Suffix collisions (same suffix, different prefix):")
        for suf, accts in suffix_collisions.items():
            print(f"    {suf} → {', '.join(accts)}")

    # ── Load DB ──
    conn = sqlite3.connect(DB_PATH, timeout=30)
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,)
    ).fetchone()
    conn.close()
    evals = json.loads(row[0] or '[]')

    # ── Audit each row ──
    problems = []
    stats = {'valid_ch': 0, 'valid_fd': 0, 'invalid_ch': 0, 'invalid_fd': 0,
             'partial_ch': 0, 'partial_fd': 0, 'empty_ch': 0, 'empty_fd': 0,
             'misplaced_ch': 0, 'misplaced_fd': 0}

    def check_account(acct, field, idx, firm):
        """Check if an account is valid. Returns (status, detail)."""
        if not acct:
            return 'empty', ''

        # Is it a full session account?
        if acct in session_accts:
            return 'valid', acct

        # Is it a suffix that resolves?
        for sa in session_accts:
            if acct == sa.rsplit('-', 1)[-1]:
                return 'partial_resolvable', f'→ {sa}'

        # Is it a partial substring match?
        matches = [sa for sa in session_accts if acct in sa]
        if len(matches) == 1:
            return 'partial_resolvable', f'→ {matches[0]}'
        elif len(matches) > 1:
            return 'ambiguous', f'matches: {", ".join(sorted(matches))}'

        # Not in session_accounts at all
        return 'invalid', f'NOT in session_accounts'

    # Detailed output
    out_lines = []
    display_total = sum(1 for ev in evals if not ev.get('_deleted'))

    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue

        display_num = display_total - idx  # approximate

        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        firm = (ev.get('Prop Firm') or '').strip()
        legacy = (ev.get('Account Number') or '').strip()

        # Check both accounts
        ch_status, ch_detail = check_account(ch, 'Account #', idx, firm)
        fd_status, fd_detail = check_account(fd, 'Account #.1', idx, firm)

        # Track stats
        if ch_status == 'valid':
            stats['valid_ch'] += 1
        elif ch_status == 'empty':
            stats['empty_ch'] += 1
        elif ch_status == 'invalid':
            stats['invalid_ch'] += 1
        elif 'partial' in ch_status or 'ambiguous' in ch_status:
            stats['partial_ch'] += 1

        if fd_status == 'valid':
            stats['valid_fd'] += 1
        elif fd_status == 'empty':
            stats['empty_fd'] += 1
        elif fd_status == 'invalid':
            stats['invalid_fd'] += 1
        elif 'partial' in fd_status or 'ambiguous' in fd_status:
            stats['partial_fd'] += 1

        # Check for misplacement: account prefix doesn't match firm
        row_problems = []

        if ch and ch_status == 'invalid':
            row_problems.append(f'  Account # = "{ch}" — {ch_detail}')

        if fd and fd_status == 'invalid':
            row_problems.append(f'  Account #.1 = "{fd}" — {fd_detail}')

        if ch and ch_status in ('partial_resolvable', 'ambiguous'):
            row_problems.append(f'  Account # = "{ch}" — unresolved partial ({ch_detail})')

        if fd and fd_status in ('partial_resolvable', 'ambiguous'):
            row_problems.append(f'  Account #.1 = "{fd}" — unresolved partial ({fd_detail})')

        # Check if eval_map has entries for this row
        map_entry = eval_map.get(str(idx))
        map_info = ''
        if map_entry:
            entries = map_entry if isinstance(map_entry, list) else [map_entry]
            map_parts = []
            for e in entries:
                if isinstance(e, dict):
                    a = e.get('account', '?')
                    p = e.get('phase', '?')
                    # Check if this map account resolves to a real session account
                    map_matches = [sa for sa in session_accts if a in sa or (a == sa.rsplit('-', 1)[-1] if '-' in sa else False)]
                    resolved = map_matches[0] if len(map_matches) == 1 else f'?({len(map_matches)} matches)' if map_matches else 'NO MATCH'
                    map_parts.append(f'{a}({p})→{resolved}')
            map_info = ' | map: ' + ', '.join(map_parts)

        if row_problems:
            problems.append((idx, display_num, firm, ch, fd, row_problems, map_info, legacy))

    # ── Print summary ──
    print(f"\n  ── Account # (Challenge) ──")
    print(f"    Valid (in session_accounts): {stats['valid_ch']}")
    print(f"    Empty: {stats['empty_ch']}")
    print(f"    Unresolved partial: {stats['partial_ch']}")
    print(f"    INVALID (not in MT5): {stats['invalid_ch']}")

    print(f"\n  ── Account #.1 (Funded) ──")
    print(f"    Valid (in session_accounts): {stats['valid_fd']}")
    print(f"    Empty: {stats['empty_fd']}")
    print(f"    Unresolved partial: {stats['partial_fd']}")
    print(f"    INVALID (not in MT5): {stats['invalid_fd']}")

    # ── Print all problems ──
    print(f"\n  ── Problem Rows ({len(problems)} total) ──")

    # Write full details to file
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_audit_chris_ream_report.txt')
    with open(out_path, 'w') as f:
        f.write(f"DEEP AUDIT: {CLIENT_ID}\n")
        f.write(f"Session accounts: {len(session_accts)}\n")
        f.write(f"Total visible rows: {display_total}\n\n")

        f.write(f"Account # valid={stats['valid_ch']} empty={stats['empty_ch']} "
                f"partial={stats['partial_ch']} INVALID={stats['invalid_ch']}\n")
        f.write(f"Account #.1 valid={stats['valid_fd']} empty={stats['empty_fd']} "
                f"partial={stats['partial_fd']} INVALID={stats['invalid_fd']}\n\n")

        f.write(f"{'='*80}\n")
        f.write(f"PROBLEM ROWS ({len(problems)}):\n")
        f.write(f"{'='*80}\n\n")

        for idx, display_num, firm, ch, fd, row_probs, map_info, legacy in problems:
            f.write(f"Row {idx} (display #{display_num}) — {firm}\n")
            f.write(f"  Account #    = '{ch}'\n")
            f.write(f"  Account #.1  = '{fd}'\n")
            if legacy:
                f.write(f"  Legacy       = '{legacy}'\n")
            if map_info:
                f.write(f"  {map_info.strip()}\n")
            for p in row_probs:
                f.write(f"  ❌ {p.strip()}\n")
            f.write(f"\n")

        # Also list ALL rows with their current state for reference
        f.write(f"\n{'='*80}\n")
        f.write(f"ALL ROWS (full state):\n")
        f.write(f"{'='*80}\n\n")
        for idx, ev in enumerate(evals):
            if ev.get('_deleted'):
                continue
            ch = (ev.get('Account #') or '').strip()
            fd = (ev.get('Account #.1') or '').strip()
            firm = (ev.get('Prop Firm') or '').strip()
            legacy = (ev.get('Account Number') or '').strip()
            ch_ok = '✓' if ch in session_accts else ('∅' if not ch else '✗')
            fd_ok = '✓' if fd in session_accts else ('∅' if not fd else '✗')
            f.write(f"  {idx:>4}: {ch_ok} CH='{ch}'  {fd_ok} FD='{fd}'  Firm='{firm}'")
            if legacy:
                f.write(f"  Legacy='{legacy}'")
            map_entry = eval_map.get(str(idx))
            if map_entry:
                entries = map_entry if isinstance(map_entry, list) else [map_entry]
                parts = []
                for e in entries:
                    if isinstance(e, dict):
                        parts.append(f"{e.get('account','?')}({e.get('phase','?')})")
                for p in parts[:4]:
                    f.write(f"  map:{p}")
                if len(parts) > 4:
                    f.write(f"  +{len(parts)-4}more")
            f.write('\n')

    # Print first 30 problems to console
    shown = 0
    for idx, display_num, firm, ch, fd, row_probs, map_info, legacy in problems:
        if shown >= 40:
            print(f"\n  ... and {len(problems) - shown} more (see full report)")
            break
        print(f"\n  Row {idx} (#{display_num}) — {firm}")
        if ch:
            print(f"    Account #   = '{ch}'")
        if fd:
            print(f"    Account #.1 = '{fd}'")
        if legacy:
            print(f"    Legacy      = '{legacy}'")
        if map_info:
            print(f"   {map_info}")
        for p in row_probs:
            print(f"    ❌{p}")
        shown += 1

    print(f"\n  Full report: {out_path}")


if __name__ == '__main__':
    main()
