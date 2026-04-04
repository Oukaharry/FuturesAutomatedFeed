#!/usr/bin/env python3
"""
Apply Chris Ream extracted log data ON TOP of the backup DB.

Run on PythonAnywhere AFTER restoring the backup:
  1.  cp dashboard/dashboard.db.pre_reconstruct_20260403_100340 dashboard/dashboard.db
  2.  python3 _apply_chris_extraction.py                  (dry run)
  3.  python3 _apply_chris_extraction.py --apply          (write to DB)
  4.  python3 _apply_chris_extraction.py --apply --csv    (write + export CSV)

This reads _chris_ream_extracted.json (pushed via git) and merges the
log-recovered hedge results, farming days, and account numbers onto
the existing Chris Ream evaluation rows in the database.

What it does:
  - Overlays hedge result writes (Hedge Result 1-5, 1.1-5.1, 6, 7)
  - Overlays farming day writes (Hedge Day 1-34)
  - Fills Account # / Account #.1 from log eval_account_map (only if DB cell is empty)
  - Derives Prop Firm from account prefix (only if DB cell is empty)
  - Recalculates Hedge Net / Hedge Net.1
  - Updates MT5 account + hedging review statistics
"""
import os, sys, json, sqlite3, csv
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_chris_ream_extracted.json')
CLIENT = "Chris Ream"

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

FIRM_TO_PREFIX = {
    'FundedNext': 'FNFT',
    'My Funded Futures': 'MFFU',
    'TradeDay': 'TDF',
    'Tradeify': 'TDFY',
    'Topstep': 'V2',
    'Alpha Futures': 'AFAD',
}

PRE_EXISTING_PREFIXES = [
    'MFFUEVSTP', 'MFFUEVSCL', 'MFFUSFSCL', 'MFFUEVFLX',
    'FTPROPLUS', 'FTPROPLUSM',
    'ELTDEN', 'ELTDFD',
    'TDFYSL', 'TDFYFD',
    'FTDFSL', 'FTDFFD',
]

DASHBOARD_COLUMN_ORDER = [
    'Prop Firm', 'Account Size', 'Date Purchased', 'Fee',
    'Date Started', 'Date Ended', 'Status P1', 'Account #',
    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
    'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
    'Account #.1', 'Activation Fee', 'Date Started.1', 'Date Ended.1', 'Status',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
    'Hedge Result 4.1', 'Hedge Result 5.1',
    'Hedge Result 6', 'Hedge Result 7', 'Hedge Net.1',
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2',
    'Payout 3', 'Date 3', 'Payout 4', 'Date 4',
] + [f'Prop Day {i}' for i in range(1, 35)] \
  + [f'Prop Progress {i}' for i in range(1, 35)] \
  + [f'Hedge Day {i}' for i in range(1, 35)]


def derive_firm(account_number):
    acct = str(account_number).strip()
    if not acct:
        return None
    upper = acct.upper()
    if '-' in acct:
        prefix = acct.rsplit('-', 1)[0].upper()
        firm = PREFIX_TO_FIRM.get(prefix)
        if firm:
            return firm
    for prefix, firm in sorted(PREFIX_TO_FIRM.items(), key=lambda x: -len(x[0])):
        if upper.startswith(prefix):
            return firm
    if acct.isdigit() and len(acct) <= 4:
        return 'Topstep'
    return None


def is_pre_existing(val):
    if not val:
        return False
    upper = str(val).upper()
    return any(upper.startswith(p) for p in PRE_EXISTING_PREFIXES)


def load_extraction():
    """Load the extracted JSON data."""
    if not os.path.exists(JSON_PATH):
        print(f"ERROR: {JSON_PATH} not found")
        print("  Run _extract_chris_local.py first, then push via git")
        sys.exit(1)
    with open(JSON_PATH) as f:
        data = json.load(f)
    print(f"  Loaded extraction: {data['total_pushes']} pushes, {data['latest_eval_count']} evals")
    print(f"  Hedge writes: {data['hedge_writes_merged']}, Farming writes: {data['farming_writes_merged']}")
    print(f"  Account maps: {data['account_map_row_count']} rows, Session accounts: {data['session_account_count']}")
    return data


def load_db_client(db_path):
    """Load Chris Ream's data from the database."""
    conn = sqlite3.connect(db_path, timeout=30)
    row = conn.execute(
        "SELECT evaluations, account, statistics, last_updated FROM clients_data WHERE client_id=?",
        (CLIENT,)
    ).fetchone()
    if not row:
        print(f"  ERROR: {CLIENT} not found in DB")
        conn.close()
        sys.exit(1)
    evals = json.loads(row[0] or '[]')
    account = json.loads(row[1] or '{}')
    stats = json.loads(row[2] or '{}')
    last_updated = row[3] or ''
    conn.close()
    print(f"  DB has {len(evals)} evaluation rows, last_updated={last_updated}")
    return evals, account, stats, last_updated


def rebuild_hedge_farm_maps(data):
    """Reconstruct the merged hedge/farm maps from the push timeline + re-parse."""
    # The JSON has summary stats but not the raw maps.
    # We need to re-extract from logs OR store them in the JSON.
    # For now, we'll use the local extraction script's output.
    # Since we're on the server, we can re-parse the server-side logs too.
    pass


def apply_extraction(db_evals, db_account, db_stats, data, session_accounts, account_maps):
    """
    Merge extracted data onto DB evaluations.
    Returns (merged_evals, merged_account, merged_stats, changes_list)
    """
    changes = []
    evals = [dict(e) for e in db_evals]  # deep copy

    # Build session account lookup: partial → full
    session_lookup = {}
    for sa in session_accounts:
        session_lookup[sa] = sa
        if '-' in sa:
            partial = sa.rsplit('-', 1)[-1]
            session_lookup[partial] = sa

    def resolve_account(partial_acct, firm=''):
        """Resolve a partial account number to full (prefix-number) form."""
        if not partial_acct or '-' in partial_acct or is_pre_existing(partial_acct):
            return partial_acct
        # 1. Direct session lookup
        full = session_lookup.get(partial_acct)
        if full and '-' in full:
            return full
        # 2. Search all session accounts for suffix match
        for sa in sorted(session_accounts):
            if '-' in sa and sa.endswith('-' + partial_acct):
                return sa
        # 3. Use Prop Firm to derive prefix
        if firm:
            prefix = FIRM_TO_PREFIX.get(firm)
            if prefix:
                return f"{prefix}-{partial_acct}"
        return partial_acct

    eval_count = len(evals)

    # ── 0. Fix existing partial Account # / Account #.1 in DB data ──
    partial_fixed = 0
    for idx, ev in enumerate(evals):
        for field in ('Account #', 'Account #.1'):
            val = ev.get(field, '').strip()
            if val and '-' not in val and not is_pre_existing(val):
                firm = ev.get('Prop Firm', '').strip()
                resolved = resolve_account(val, firm)
                if resolved != val:
                    ev[field] = resolved
                    partial_fixed += 1
                    changes.append(f"[FIX] Row {idx} {field}: {val} -> {resolved}")
    print(f"  Partial account numbers fixed: {partial_fixed}")

    # ── 1. Place account numbers from account_maps ──
    acct_placed = 0
    acct_skipped = 0
    for row_str, entries in account_maps.items():
        row_idx = int(row_str)
        if row_idx >= eval_count:
            continue
        for entry in entries:
            acct = entry['account']
            phase = entry['phase'].upper()
            full_acct = resolve_account(acct)

            if phase.startswith('CH'):
                field = 'Account #'
            elif phase in ('FA', 'FD', 'DD'):
                field = 'Account #.1'
            else:
                field = 'Account #'

            existing = evals[row_idx].get(field, '').strip()
            # Only fill if empty or not a pre-existing MT5 value
            if not existing:
                evals[row_idx][field] = full_acct
                acct_placed += 1
                changes.append(f"[ACCT] Row {row_idx} {field} = {full_acct}")
                break
            elif is_pre_existing(existing):
                acct_skipped += 1
                break
            else:
                acct_skipped += 1
                break

    print(f"  Account numbers placed: {acct_placed}, skipped: {acct_skipped}")

    # ── 2. Derive Prop Firm ──
    firm_count = 0
    for idx, ev in enumerate(evals):
        if ev.get('Prop Firm', '').strip():
            continue
        acct = ev.get('Account #', '').strip() or ev.get('Account #.1', '').strip()
        if acct:
            firm = derive_firm(acct)
            if firm:
                ev['Prop Firm'] = firm
                firm_count += 1
                changes.append(f"[FIRM] Row {idx} Prop Firm = {firm}")
    print(f"  Prop Firm derived: {firm_count}")

    # ── 2b. Fix any new partials that now have a Prop Firm ──
    partial_fixed_2 = 0
    for idx, ev in enumerate(evals):
        for field in ('Account #', 'Account #.1'):
            val = ev.get(field, '').strip()
            if val and '-' not in val and not is_pre_existing(val):
                firm = ev.get('Prop Firm', '').strip()
                resolved = resolve_account(val, firm)
                if resolved != val:
                    ev[field] = resolved
                    partial_fixed_2 += 1
                    changes.append(f"[FIX2] Row {idx} {field}: {val} -> {resolved}")
    if partial_fixed_2:
        print(f"  Additional partial fixes (post-firm): {partial_fixed_2}")

    # ── 3. We'll handle hedge/farming overlays from raw push data ──
    # These are stored separately — see apply_hedge_farming_data()

    # ── 4. Update account dict ──
    scalars = data.get('scalars', {})
    account = dict(db_account)
    if scalars.get('mt5_balance') is not None:
        old = account.get('balance', 'N/A')
        account['balance'] = scalars['mt5_balance']
        changes.append(f"[MT5] account.balance = {scalars['mt5_balance']} (was {old})")
    if scalars.get('mt5_deposits') is not None:
        old = account.get('total_deposits', 'N/A')
        account['total_deposits'] = scalars['mt5_deposits']
        changes.append(f"[MT5] account.total_deposits = {scalars['mt5_deposits']} (was {old})")
    if scalars.get('mt5_withdrawals') is not None:
        old = account.get('total_withdrawals', 'N/A')
        account['total_withdrawals'] = scalars['mt5_withdrawals']
        changes.append(f"[MT5] account.total_withdrawals = {scalars['mt5_withdrawals']} (was {old})")

    # ── 5. Update hedging review stats ──
    stats = dict(db_stats)
    hr = dict(stats.get('hedging_review', {}))
    if scalars.get('hr_deposits') is not None:
        hr['total_deposits'] = scalars['hr_deposits']
    if scalars.get('hr_withdrawals') is not None:
        hr['total_withdrawals'] = scalars['hr_withdrawals']
    if scalars.get('hr_balance') is not None:
        hr['current_balance'] = scalars['hr_balance']
    if scalars.get('stats_hedging') is not None:
        hr['actual_hedging_results'] = scalars['stats_hedging']
    stats['hedging_review'] = hr
    changes.append(f"[HR] Updated hedging_review")

    return evals, account, stats, changes


def export_csv(evals, output_path):
    """Export evaluations as dashboard-format CSV."""
    all_keys = set()
    for ev in evals:
        all_keys.update(ev.keys())

    columns = ['Row #']
    for c in DASHBOARD_COLUMN_ORDER:
        columns.append(c)
    extra = sorted(all_keys - set(DASHBOARD_COLUMN_ORDER) - {'Row #'})
    for c in extra:
        if not c.startswith('_'):
            columns.append(c)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for idx, ev in enumerate(evals):
            row = dict(ev)
            row['Row #'] = idx
            writer.writerow(row)

    print(f"  CSV exported: {output_path} ({len(columns)} columns, {len(evals)} rows)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Apply Chris Ream extracted data to DB')
    parser.add_argument('--apply', action='store_true', help='Write changes to DB (default: dry run)')
    parser.add_argument('--csv', action='store_true', help='Export CSV after applying')
    parser.add_argument('--db', help='Custom DB path', default=DB_PATH)
    args = parser.parse_args()

    print("=" * 70)
    print(f"  {'APPLYING' if args.apply else 'DRY RUN'}: Chris Ream extraction -> DB")
    print("=" * 70)

    # Load extraction data
    print("\n-- Loading extraction --")
    data = load_extraction()

    # Load DB
    print("\n-- Loading DB --")
    db_evals, db_account, db_stats, db_last_updated = load_db_client(args.db)

    session_accounts = data.get('session_accounts', [])
    account_maps = data.get('account_maps', {})

    # Apply
    print("\n-- Applying extraction --")
    evals, account, stats, changes = apply_extraction(
        db_evals, db_account, db_stats, data, session_accounts, account_maps
    )

    # ── Apply hedge result + farming day writes ──
    hedge_writes = data.get('hedge_writes', [])
    farm_writes = data.get('farming_writes', [])
    eval_count = len(evals)

    hedge_ok = 0
    for hw in hedge_writes:
        row, col, val = hw['row'], hw['col'], hw['val']
        if 0 <= row < eval_count:
            old = evals[row].get(col, '')
            evals[row][col] = f"{val:.2f}"
            hedge_ok += 1
            if hedge_ok <= 20:
                changes.append(f"[HEDGE] Row {row} [{col}] = ${val:.2f} (was {old})")
    print(f"  Hedge writes applied: {hedge_ok}/{len(hedge_writes)}")

    farm_ok = 0
    for fw in farm_writes:
        row, day, val, date_str = fw['row'], fw['day'], fw['val'], fw['date']
        if 0 <= row < eval_count:
            field = f'Hedge Day {day}'
            evals[row][field] = f"{val:.2f}"
            farm_ok += 1
            changes.append(f"[FARM] Row {row} [{field}] = ${val:.2f} ({date_str})")
    print(f"  Farming writes applied: {farm_ok}/{len(farm_writes)}")

    # ── Recalculate Hedge Net / Hedge Net.1 ──
    net_count = 0
    for ev in evals:
        for cols, net_field in [
            (['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
              'Hedge Result 4', 'Hedge Result 5'], 'Hedge Net'),
            (['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
              'Hedge Result 4.1', 'Hedge Result 5.1',
              'Hedge Result 6', 'Hedge Result 7'], 'Hedge Net.1'),
        ]:
            vals = []
            for c in cols:
                v = ev.get(c, '')
                if v:
                    try:
                        vals.append(float(str(v).replace('$', '').replace(',', '')))
                    except ValueError:
                        pass
            if vals:
                ev[net_field] = f"{sum(vals):.2f}"
                net_count += 1
    print(f"  Hedge Net recalculated: {net_count} cells")

    # Show changes
    print(f"\n  Total changes: {len(changes)}")
    if changes:
        for c in changes[:30]:
            print(f"    {c}")
        if len(changes) > 30:
            print(f"    ... and {len(changes) - 30} more")

    # Summary
    has_acct = sum(1 for e in evals if e.get('Account #', '').strip())
    has_acct1 = sum(1 for e in evals if e.get('Account #.1', '').strip())
    has_firm = sum(1 for e in evals if e.get('Prop Firm', '').strip())
    has_hr = sum(1 for e in evals if e.get('Hedge Result 1', '').strip())
    print(f"\n  After merge:")
    print(f"    Total rows:    {len(evals)}")
    print(f"    Account #:     {has_acct}")
    print(f"    Account #.1:   {has_acct1}")
    print(f"    Prop Firm:     {has_firm}")
    print(f"    Hedge Result 1:{has_hr}")

    if args.apply:
        print("\n-- Writing to DB --")
        conn = sqlite3.connect(args.db, timeout=30)
        conn.execute(
            "UPDATE clients_data SET evaluations=?, account=?, statistics=?, last_updated=? WHERE client_id=?",
            (json.dumps(evals), json.dumps(account), json.dumps(stats),
             data.get('latest_timestamp', db_last_updated), CLIENT)
        )
        conn.commit()
        conn.close()
        print("  Done.")

    if args.csv:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                f'_export_Chris_Ream.csv')
        export_csv(evals, csv_path)

    if not args.apply:
        print("\n  [DRY RUN] — use --apply to write changes")


if __name__ == '__main__':
    main()
