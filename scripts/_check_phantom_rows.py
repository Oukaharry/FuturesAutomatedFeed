#!/usr/bin/env python3
"""
Check Chris Ream for phantom rows — rows with no account data that
may have been artificially created by reconstruction scripts.

Cross-references:
1. Current DB: Account #, Account #.1, Account Number
2. eval_account_map from push report  
3. Identifies rows with NO account source at all

Usage:
    python3 _check_phantom_rows.py
"""
import sqlite3, json, os

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')
CLIENT_ID = 'Chris Ream'

PRE_EXISTING_PREFIXES = (
    'MFFUEVSTP', 'MFFUEVSCL', 'MFFUSFSCL', 'MFFUSFSTP',
    'FTPROPLUS', 'FTPROPLUSM',
    'ELTDEN', 'ELTDFD',
    'TDFYSL', 'TDFYFD',
    'FTDFSL', 'FTDFFD',
)


def is_pre_existing(acct):
    if not acct:
        return False
    upper = acct.upper()
    for prefix in PRE_EXISTING_PREFIXES:
        if upper.startswith(prefix) and len(acct) > 12:
            return True
    return False


def main():
    # Load push report
    with open(REPORT_PATH) as f:
        report = json.load(f)
    client_report = report.get('clients', {}).get(CLIENT_ID, {})
    session_accts = set(client_report.get('session_accounts', []))
    eval_map = client_report.get('eval_account_map', {})

    # Load DB
    conn = sqlite3.connect(DB_PATH, timeout=30)
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id=?", (CLIENT_ID,)
    ).fetchone()
    conn.close()
    evals = json.loads(row[0] or '[]')

    total = len(evals)
    deleted = sum(1 for ev in evals if ev.get('_deleted'))
    visible = total - deleted

    print(f"\n{'='*70}")
    print(f"  PHANTOM ROW CHECK: {CLIENT_ID}")
    print(f"{'='*70}")
    print(f"  Total rows: {total}  (deleted: {deleted}, visible: {visible})")
    print(f"  eval_account_map covers: {len(eval_map)} rows")
    print(f"  Session accounts: {len(session_accts)}")

    # Categorize every row
    has_pre_existing = []     # Has long MT5 account strings (pre-crash data)
    has_session_acct = []     # Has valid session account
    has_map_entry = []        # Has eval_account_map entry
    has_legacy_only = []      # Only has legacy Account Number
    has_hedge_data = []       # Has hedge results (evidence of real usage)
    phantom_rows = []         # NO account source at all
    has_any_content = []      # Has any non-empty field besides structure

    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue

        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        legacy = (ev.get('Account Number') or '').strip()
        firm = (ev.get('Prop Firm') or '').strip()
        has_map = str(idx) in eval_map

        # Check account sources
        pre_ex = is_pre_existing(ch) or is_pre_existing(fd)
        valid_session = (ch in session_accts) or (fd in session_accts) or (legacy in session_accts)

        # Check if row has any substantive data
        hedge_keys = [f'Hedge Result {i}' for i in range(1, 6)] + \
                     [f'Hedge Result {i}.1' for i in range(1, 6)] + \
                     [f'Hedge Day {i}' for i in range(1, 35)]
        has_hedge = any((ev.get(k) or '').strip() for k in hedge_keys)

        date_keys = ['Date Started', 'Date Ended', 'Date Started.1', 'Date Ended.1',
                     'Date Purchased']
        has_dates = any((ev.get(k) or '').strip() for k in date_keys)

        payout_keys = [f'Payout {i}' for i in range(1, 5)]
        has_payouts = any((ev.get(k) or '').strip() for k in payout_keys)

        status = (ev.get('Status P1') or ev.get('Status') or '').strip()

        content_fields = 0
        for k, v in ev.items():
            if k.startswith('_'):
                continue
            if (v or '') and str(v).strip():
                content_fields += 1

        if pre_ex:
            has_pre_existing.append(idx)
        if valid_session:
            has_session_acct.append(idx)
        if has_map:
            has_map_entry.append(idx)
        if legacy and not valid_session and not pre_ex:
            has_legacy_only.append(idx)
        if has_hedge:
            has_hedge_data.append(idx)

        # PHANTOM: no pre-existing account, no session account, no map entry
        # and no legacy account
        if not pre_ex and not valid_session and not has_map and not legacy:
            phantom_rows.append({
                'idx': idx,
                'display': visible - idx,
                'firm': firm,
                'status': status,
                'ch': ch,
                'fd': fd,
                'has_hedge': has_hedge,
                'has_dates': has_dates,
                'has_payouts': has_payouts,
                'content_fields': content_fields,
            })

    # Also check: rows where ONLY source is eval_account_map (no pre-existing account)
    map_only_rows = []
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        legacy = (ev.get('Account Number') or '').strip()
        pre_ex = is_pre_existing(ch) or is_pre_existing(fd)
        valid_session = (ch in session_accts) or (fd in session_accts) or (legacy in session_accts)
        has_map = str(idx) in eval_map

        if not pre_ex and has_map and not valid_session:
            map_only_rows.append(idx)

    print(f"\n  ── Row Sources ──")
    print(f"  Has pre-existing MT5 account: {len(has_pre_existing)}")
    print(f"  Has valid session account: {len(has_session_acct)}")
    print(f"  Has eval_account_map entry: {len(has_map_entry)}")
    print(f"  Has hedge result data: {len(has_hedge_data)}")
    print(f"  Has only legacy Account Number: {len(has_legacy_only)}")
    print(f"  Map entry only (no pre-existing/session): {len(map_only_rows)}")
    print(f"  PHANTOM (no account source at all): {len(phantom_rows)}")

    # Show phantoms
    if phantom_rows:
        print(f"\n  ── Phantom Rows — NO account source ({len(phantom_rows)}) ──")
        # Group by content level
        empty_phantoms = [p for p in phantom_rows if p['content_fields'] <= 3]
        data_phantoms = [p for p in phantom_rows if p['content_fields'] > 3]

        if data_phantoms:
            print(f"\n  Phantoms WITH data ({len(data_phantoms)}):")
            for p in data_phantoms[:30]:
                print(f"    row {p['idx']:>4} (#{p['display']:>3}) — {p['firm'] or '(no firm)':20s}"
                      f"  status={p['status'] or '?':15s}  fields={p['content_fields']}"
                      f"  hedge={'Y' if p['has_hedge'] else 'N'}  dates={'Y' if p['has_dates'] else 'N'}")
            if len(data_phantoms) > 30:
                print(f"    ... and {len(data_phantoms)-30} more")

        if empty_phantoms:
            print(f"\n  Near-empty phantoms ({len(empty_phantoms)}):")
            for p in empty_phantoms[:20]:
                print(f"    row {p['idx']:>4} (#{p['display']:>3}) — {p['firm'] or '(no firm)':20s}"
                      f"  status={p['status'] or '?':15s}  fields={p['content_fields']}"
                      f"  ch='{p['ch']}'  fd='{p['fd']}'")
            if len(empty_phantoms) > 20:
                print(f"    ... and {len(empty_phantoms)-20} more")

    # Write full detail
    rpt = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_phantom_rows_report.txt')
    with open(rpt, 'w') as f:
        f.write(f"PHANTOM ROW CHECK: {CLIENT_ID}\n")
        f.write(f"Total visible: {visible}\n")
        f.write(f"Phantoms: {len(phantom_rows)}\n\n")

        for p in phantom_rows:
            idx = p['idx']
            ev = evals[idx]
            f.write(f"Row {idx} (#{p['display']}) — {p['firm']}\n")
            for k, v in sorted(ev.items()):
                if k.startswith('_'):
                    continue
                v_str = str(v or '').strip()
                if v_str:
                    f.write(f"  {k}: {v_str}\n")
            f.write('\n')

        f.write(f"\n{'='*70}\n")
        f.write(f"Map-only rows (no pre-existing, no session acct): {len(map_only_rows)}\n")
        for idx in map_only_rows:
            ev = evals[idx]
            ch = (ev.get('Account #') or '').strip()
            fd = (ev.get('Account #.1') or '').strip()
            firm = (ev.get('Prop Firm') or '').strip()
            entries = eval_map.get(str(idx), [])
            if not isinstance(entries, list):
                entries = [entries]
            map_str = ', '.join(
                f"{e.get('account','?')}({e.get('phase','?')})" if isinstance(e, dict) else str(e)
                for e in entries
            )
            f.write(f"  row {idx}: CH='{ch}' FD='{fd}' Firm='{firm}'  map=[{map_str}]\n")

    print(f"\n  Full report: {rpt}")


if __name__ == '__main__':
    main()
