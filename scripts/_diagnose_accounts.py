#!/usr/bin/env python3
"""
Diagnose why Account # / Account #.1 are empty for a client.

Checks:
1. What's in the push report's eval_account_map for this client
2. What's currently in DB: Account #, Account #.1, Account Number
3. What session_accounts are available
4. Summary of populated vs empty rows

Usage:
    python3 _diagnose_accounts.py "Chris Ream"
"""
import sqlite3, json, os, sys

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')


def main():
    client_id = sys.argv[1] if len(sys.argv) > 1 else 'Chris Ream'

    # ── Load push report ──
    report = {}
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH) as f:
            report = json.load(f)

    client_report = report.get('clients', {}).get(client_id, {})
    eval_map = client_report.get('eval_account_map', {})
    session_accts = client_report.get('session_accounts', [])

    print(f"\n{'='*70}")
    print(f"  ACCOUNT DIAGNOSIS: {client_id}")
    print(f"{'='*70}")

    # Push report data
    print(f"\n  ── Push Report ──")
    if not client_report:
        print(f"    ⚠ No push report entry for {client_id}")
    else:
        print(f"    Session accounts ({len(session_accts)}):")
        for sa in sorted(session_accts):
            print(f"      {sa}")

        print(f"\n    eval_account_map ({len(eval_map)} row entries):")
        for idx in sorted(eval_map.keys(), key=lambda x: int(x)):
            entries = eval_map[idx]
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict):
                        print(f"      row {idx}: account={e.get('account','?')}  phase={e.get('phase','?')}  num={e.get('num','?')}")
                    else:
                        print(f"      row {idx}: {e}")
            elif isinstance(entries, dict):
                print(f"      row {idx}: account={entries.get('account','?')}  phase={entries.get('phase','?')}  num={entries.get('num','?')}")
            else:
                print(f"      row {idx}: {entries}")

    # ── DB data ──
    print(f"\n  ── Database State ──")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    row = conn.execute(
        "SELECT evaluations FROM clients_data WHERE client_id=?", (client_id,)
    ).fetchone()
    conn.close()

    if not row:
        print(f"    ⚠ Client not found in DB")
        return

    evals = json.loads(row[0] or '[]')
    total = len(evals)
    deleted = sum(1 for ev in evals if ev.get('_deleted'))
    visible = total - deleted

    has_acct_ch = 0
    has_acct_fd = 0
    has_acct_legacy = 0
    has_any_acct = 0
    empty_all_acct = 0

    # Show first 30 rows with any account data
    print(f"\n    Total rows: {total}  (deleted: {deleted}, visible: {visible})")
    print(f"\n    Rows with account data (showing first 50):")
    shown = 0
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        legacy = (ev.get('Account Number') or '').strip()
        firm = (ev.get('Prop Firm') or '').strip()

        if ch:
            has_acct_ch += 1
        if fd:
            has_acct_fd += 1
        if legacy:
            has_acct_legacy += 1
        if ch or fd or legacy:
            has_any_acct += 1
            if shown < 50:
                print(f"      row {idx}: CH='{ch}'  FD='{fd}'  Legacy='{legacy}'  Firm='{firm}'")
                shown += 1
        else:
            empty_all_acct += 1

    print(f"\n    Summary:")
    print(f"      Account # (challenge) populated: {has_acct_ch} / {visible}")
    print(f"      Account #.1 (funded) populated: {has_acct_fd} / {visible}")
    print(f"      Account Number (legacy) populated: {has_acct_legacy} / {visible}")
    print(f"      ANY account field populated: {has_any_acct} / {visible}")
    print(f"      ALL account fields empty: {empty_all_acct} / {visible}")

    # ── Check if session_accounts could fill rows via hedge results ──
    print(f"\n  ── Rows with hedge results but no account ──")
    shown = 0
    for idx, ev in enumerate(evals):
        if ev.get('_deleted'):
            continue
        ch = (ev.get('Account #') or '').strip()
        fd = (ev.get('Account #.1') or '').strip()
        legacy = (ev.get('Account Number') or '').strip()
        if ch or fd or legacy:
            continue

        has_hr = []
        for i in range(1, 6):
            v = (ev.get(f'Hedge Result {i}') or '').strip()
            if v:
                has_hr.append(f'HR{i}={v}')
        for i in range(1, 6):
            v = (ev.get(f'Hedge Result {i}.1') or '').strip()
            if v:
                has_hr.append(f'HR{i}.1={v}')
        if has_hr and shown < 20:
            firm = (ev.get('Prop Firm') or '').strip()
            print(f"      row {idx}: Firm={firm}  {', '.join(has_hr[:5])}")
            shown += 1


if __name__ == '__main__':
    main()
