#!/usr/bin/env python3
"""
RECOVERY VERIFICATION & AUDIT REPORT
=====================================
1. Confirms the live DB has the missing week's data (March 26 - April 1)
2. Identifies which clients are missing daily data for each day
3. Shows audit_log activity for non-push clients (prioritized for manual re-entry)
4. Compares reconstructed backup vs live DB
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
BACKUP_PATTERN = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard_reconstructed_*.db')

# The missing week
MISSING_START = '2026-03-26'
MISSING_END = '2026-04-01'
MISSING_DATES = []
d = datetime(2026, 3, 26)
while d <= datetime(2026, 4, 1):
    MISSING_DATES.append(d.strftime('%Y-%m-%d'))
    d += timedelta(days=1)


def get_latest_backup():
    """Find the most recent reconstructed backup DB."""
    import glob
    backups = sorted(glob.glob(BACKUP_PATTERN))
    return backups[-1] if backups else None


def analyze_client_daily_coverage(db_path):
    """
    For each client, check evaluations for daily data coverage.
    
    Farming days have _Hedge Day N Date fields with YYYY-MM-DD dates.
    Hedge results are positional (no date) but we can check if they exist.
    
    Returns per-client coverage info.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT client_id, evaluations, last_updated,
               hedge_accounts, prop_accounts, vps_accounts
        FROM clients_data ORDER BY client_id
    ''').fetchall()
    conn.close()

    clients = []
    for row in rows:
        cid = row['client_id']
        evals = json.loads(row['evaluations'] or '[]')
        last_updated = row['last_updated'] or ''
        hedge_accts = json.loads(row['hedge_accounts'] or '[]')
        prop_accts = json.loads(row['prop_accounts'] or '[]')
        vps_accts = json.loads(row['vps_accounts'] or '[]')

        # Collect all farming dates across all eval rows
        farming_dates = set()
        hedge_result_count = 0
        total_evals = len(evals)

        for ev in evals:
            # Check farming day dates
            for n in range(1, 51):
                date_key = f'_Hedge Day {n} Date'
                val_key = f'Hedge Day {n}'
                date_val = ev.get(date_key, '')
                day_val = ev.get(val_key, '')
                if date_val and str(date_val).strip():
                    farming_dates.add(str(date_val).strip())

            # Count hedge results (any non-empty)
            for col in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                        'Hedge Result 4', 'Hedge Result 5',
                        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                        'Hedge Result 4.1', 'Hedge Result 5.1',
                        'Hedge Result 6', 'Hedge Result 7']:
                val = ev.get(col, '')
                if val and str(val).strip() and str(val).strip() != '0':
                    hedge_result_count += 1

        # Which missing week dates have farming data?
        missing_week_farming = set()
        for date in MISSING_DATES:
            if date in farming_dates:
                missing_week_farming.add(date)

        # Check dates BEFORE the missing week for baseline
        pre_week_dates = set()
        for fd in farming_dates:
            if fd < MISSING_START:
                pre_week_dates.add(fd)

        # Check dates AFTER the missing week
        post_week_dates = set()
        for fd in farming_dates:
            if fd > MISSING_END:
                post_week_dates.add(fd)

        clients.append({
            'client_id': cid,
            'last_updated': last_updated,
            'total_evals': total_evals,
            'hedge_result_count': hedge_result_count,
            'all_farming_dates': sorted(farming_dates),
            'missing_week_covered': sorted(missing_week_farming),
            'missing_week_gaps': sorted(set(MISSING_DATES) - missing_week_farming),
            'pre_week_dates': len(pre_week_dates),
            'post_week_dates': len(post_week_dates),
            'hedge_accounts': len(hedge_accts),
            'prop_accounts': len(prop_accts),
            'vps_accounts': len(vps_accts),
        })

    return clients


def get_audit_log_activity(db_path):
    """
    Query audit_log for all activity during the missing week.
    Group by client and action type.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    entries = []
    try:
        rows = conn.execute('''
            SELECT timestamp, action, user_identifier, details
            FROM audit_log
            WHERE timestamp >= ? AND timestamp < '2026-04-02'
            ORDER BY timestamp
        ''', (MISSING_START,)).fetchall()
        entries = [dict(r) for r in rows]
    except Exception as e:
        print(f"  Error querying audit_log: {e}")

    conn.close()

    # Group by client
    client_activity = defaultdict(lambda: defaultdict(int))
    client_timestamps = defaultdict(list)

    for entry in entries:
        detail = (entry.get('details') or '')
        action = entry.get('action', '?')
        ts = entry.get('timestamp', '')

        if 'Client:' in detail:
            cid = detail.split('Client:')[1].split('(')[0].strip()
            client_activity[cid][action] += 1
            client_timestamps[cid].append(ts)

    return client_activity, client_timestamps, entries


def main():
    print("=" * 100)
    print("RECOVERY VERIFICATION & DATA GAP ANALYSIS")
    print(f"Time: {datetime.now()}")
    print(f"Missing Week: {MISSING_START} → {MISSING_END} ({len(MISSING_DATES)} days)")
    print("=" * 100)

    # ── 1. DAILY COVERAGE CHECK ──
    print(f"\n{'='*80}")
    print("SECTION 1: DAILY FARMING DATA COVERAGE (LIVE DB)")
    print(f"{'='*80}\n")

    clients = analyze_client_daily_coverage(DB_PATH)

    # Categorize clients
    fully_covered = []  # Has farming data for ALL 7 missing days
    partially_covered = []  # Has farming data for SOME missing days
    no_week_data = []  # Has NO farming data for any missing day
    no_farming_at_all = []  # Has zero farming dates ever

    for c in clients:
        if not c['all_farming_dates']:
            no_farming_at_all.append(c)
        elif len(c['missing_week_covered']) == len(MISSING_DATES):
            fully_covered.append(c)
        elif len(c['missing_week_covered']) > 0:
            partially_covered.append(c)
        else:
            no_week_data.append(c)

    print(f"  Total clients: {len(clients)}")
    print(f"  ✅ Full week coverage (all {len(MISSING_DATES)} days): {len(fully_covered)}")
    print(f"  ⚠️  Partial week coverage:                    {len(partially_covered)}")
    print(f"  ❌ No missing week data:                      {len(no_week_data)}")
    print(f"  ⬜ No farming data ever (non-farming clients): {len(no_farming_at_all)}")

    if fully_covered:
        print(f"\n  ✅ FULLY RECOVERED ({len(fully_covered)}):")
        for c in sorted(fully_covered, key=lambda x: x['client_id']):
            print(f"    {c['client_id']:<30} {len(c['all_farming_dates'])} farming dates total, "
                  f"evals={c['total_evals']}, HR={c['hedge_result_count']}")

    if partially_covered:
        print(f"\n  ⚠️  PARTIALLY RECOVERED ({len(partially_covered)}):")
        for c in sorted(partially_covered, key=lambda x: x['client_id']):
            covered = c['missing_week_covered']
            gaps = c['missing_week_gaps']
            print(f"    {c['client_id']:<30} has {len(covered)}/{len(MISSING_DATES)} days | "
                  f"MISSING: {', '.join(gaps)}")

    if no_week_data:
        print(f"\n  ❌ NO MISSING WEEK DATA ({len(no_week_data)}):")
        for c in sorted(no_week_data, key=lambda x: x['client_id']):
            latest_farming = c['all_farming_dates'][-1] if c['all_farming_dates'] else 'none'
            print(f"    {c['client_id']:<30} latest farming date: {latest_farming}, "
                  f"evals={c['total_evals']}, HR={c['hedge_result_count']}")

    # ── 2. HEDGE RESULT COVERAGE ──
    print(f"\n{'='*80}")
    print("SECTION 2: HEDGE RESULT DATA PRESENCE")
    print(f"{'='*80}\n")

    has_hedge_results = [c for c in clients if c['hedge_result_count'] > 0]
    no_hedge_results = [c for c in clients if c['hedge_result_count'] == 0 and c['total_evals'] > 0]

    print(f"  Clients with hedge results: {len(has_hedge_results)}")
    print(f"  Clients with evals but NO hedge results: {len(no_hedge_results)}")

    if no_hedge_results:
        print(f"\n  Clients with evaluations but zero hedge results:")
        for c in sorted(no_hedge_results, key=lambda x: -x['total_evals']):
            print(f"    {c['client_id']:<30} evals={c['total_evals']}")

    # ── 3. AUDIT LOG ANALYSIS FOR NON-PUSH CLIENTS ──
    print(f"\n{'='*80}")
    print("SECTION 3: AUDIT LOG — NON-PUSH CLIENT ACTIVITY (PRIORITIZED)")
    print(f"{'='*80}\n")

    client_activity, client_timestamps, all_entries = get_audit_log_activity(DB_PATH)

    # Identify non-push clients (no farming data in missing week AND last_updated before April 2)
    push_clients_with_data = set(c['client_id'] for c in clients
                                  if c['missing_week_covered'])

    non_push_with_edits = []
    non_push_no_edits = []

    for c in clients:
        cid = c['client_id']
        if cid in push_clients_with_data:
            continue  # Already has recovered data

        activity = client_activity.get(cid, {})
        total_edits = sum(activity.values())
        data_updates = activity.get('DATA_UPDATE', 0)
        note_updates = activity.get('UPDATE_NOTE', 0)
        pushes = activity.get('CLIENT_DATA_PUSH', 0)

        timestamps = client_timestamps.get(cid, [])
        first_edit = min(timestamps) if timestamps else ''
        last_edit = max(timestamps) if timestamps else ''

        info = {
            **c,
            'total_edits': total_edits,
            'data_updates': data_updates,
            'note_updates': note_updates,
            'push_count': pushes,
            'first_edit': first_edit,
            'last_edit': last_edit,
            'activity': dict(activity),
        }

        if total_edits > 0:
            non_push_with_edits.append(info)
        else:
            non_push_no_edits.append(info)

    # Sort by edit count descending (most active = highest priority)
    non_push_with_edits.sort(key=lambda x: -x['total_edits'])

    print(f"  Clients WITHOUT recovered week data: {len(non_push_with_edits) + len(non_push_no_edits)}")
    print(f"    With audit_log edits during the week: {len(non_push_with_edits)} ← NEED MANUAL RECOVERY")
    print(f"    No audit_log edits during the week:   {len(non_push_no_edits)} ← Likely untouched")

    if non_push_with_edits:
        print(f"\n  🔴 PRIORITY: CLIENTS NEEDING MANUAL DATA RE-ENTRY")
        print(f"  {'Client':<30} {'Edits':>6} {'Updates':>8} {'Notes':>6} {'Pushes':>7} {'First Edit':<20} {'Last Edit':<20}")
        print(f"  {'─'*30} {'─'*6} {'─'*8} {'─'*6} {'─'*7} {'─'*20} {'─'*20}")
        for info in non_push_with_edits:
            print(f"  {info['client_id']:<30} {info['total_edits']:>6} {info['data_updates']:>8} "
                  f"{info['note_updates']:>6} {info['push_count']:>7} "
                  f"{info['first_edit'][:19]:<20} {info['last_edit'][:19]:<20}")

        print(f"\n  Detailed breakdown per client:")
        for info in non_push_with_edits:
            print(f"\n    📋 {info['client_id']} ({info['total_edits']} total edits)")
            print(f"       Current state: evals={info['total_evals']}, "
                  f"hedge_accts={info['hedge_accounts']}, prop_accts={info['prop_accounts']}, "
                  f"vps_accts={info['vps_accounts']}")
            print(f"       Last DB update: {info['last_updated']}")
            for action, count in sorted(info['activity'].items()):
                print(f"       {action}: {count}")

    if non_push_no_edits:
        print(f"\n  ⬜ LIKELY UNTOUCHED (no audit_log edits during the week):")
        for info in sorted(non_push_no_edits, key=lambda x: x['client_id']):
            print(f"    {info['client_id']:<30} last_updated={info['last_updated'][:19] if info['last_updated'] else 'None':<20} "
                  f"evals={info['total_evals']}")

    # ── 4. DAY-BY-DAY SUMMARY ──
    print(f"\n{'='*80}")
    print("SECTION 4: DAY-BY-DAY FARMING DATA COVERAGE")
    print(f"{'='*80}\n")

    print(f"  {'Date':<12} {'Clients with data':>18} {'Clients missing':>16}")
    print(f"  {'─'*12} {'─'*18} {'─'*16}")

    for date in MISSING_DATES:
        has_data = sum(1 for c in clients if date in c['missing_week_covered'])
        missing = sum(1 for c in clients
                      if c['all_farming_dates'] and date not in c['missing_week_covered'])
        print(f"  {date:<12} {has_data:>18} {missing:>16}")

    # ── 5. OVERALL HEALTH CHECK ──
    print(f"\n{'='*80}")
    print("SECTION 5: OVERALL DATABASE HEALTH")
    print(f"{'='*80}\n")

    # Check last_updated freshness
    stale_clients = []
    fresh_clients = []
    for c in clients:
        lu = c['last_updated']
        if lu and lu[:10] >= '2026-04-02':
            fresh_clients.append(c)
        else:
            stale_clients.append(c)

    print(f"  Clients with last_updated >= April 2: {len(fresh_clients)} ✅")
    print(f"  Clients with last_updated < April 2:  {len(stale_clients)} ⚠️")

    if stale_clients:
        print(f"\n  Stale clients (last_updated before April 2):")
        for c in sorted(stale_clients, key=lambda x: x['last_updated'] or ''):
            print(f"    {c['client_id']:<30} last_updated={c['last_updated'] or 'None'}")

    # Compare with backup if it exists
    backup_path = get_latest_backup()
    if backup_path:
        print(f"\n{'─'*80}")
        print(f"  Backup DB: {backup_path}")
        backup_clients = analyze_client_daily_coverage(backup_path)
        backup_map = {c['client_id']: c for c in backup_clients}
        live_map = {c['client_id']: c for c in clients}

        diffs = 0
        for cid in sorted(live_map.keys()):
            live = live_map[cid]
            backup = backup_map.get(cid)
            if not backup:
                continue
            if live['missing_week_covered'] != backup['missing_week_covered']:
                print(f"  ⚠️  {cid}: live has {len(live['missing_week_covered'])} days, "
                      f"backup has {len(backup['missing_week_covered'])} days")
                diffs += 1
        if diffs == 0:
            print(f"  ✅ Live DB and backup DB have identical missing-week farming coverage")
    else:
        print(f"\n  No reconstructed backup DB found")

    # ── FINAL SUMMARY ──
    print(f"\n{'='*100}")
    print("FINAL SUMMARY")
    print(f"{'='*100}")
    print(f"""
  RECOVERY STATUS:
    ✅ Push clients fully reconstructed:     {len(fully_covered) + len(partially_covered)} / {len(clients)}
    ❌ Clients needing manual re-entry:      {len(non_push_with_edits)}
    ⬜ Clients likely untouched:             {len(non_push_no_edits)}
    
  DATA GAPS:
    Farming dates missing for active clients: {sum(len(c['missing_week_gaps']) for c in partially_covered)}
    Clients with zero week coverage:          {len(no_week_data)}
    
  TOP PRIORITY FOR MANUAL RECOVERY:""")
    for info in non_push_with_edits[:10]:
        print(f"    {info['client_id']:<30} {info['data_updates']} dashboard edits during the week")

    print(f"\n{'='*100}")
    print("VERIFICATION COMPLETE")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
