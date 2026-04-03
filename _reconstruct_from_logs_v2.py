#!/usr/bin/env python3
"""
RECONSTRUCT CLIENT DATA FROM SERVER LOGS (Mar 25 - Apr 2)  —  V2

The push flow logs every cell write with values, allowing near-perfect
reconstruction of the missing week's data. This script:

  1.  Parses ALL rotated error logs chronologically (Mar 25 → Apr 2)
  2.  Extracts EVERY push event for each client with all cell writes:
        ✅ Matched session  →  Column: [Hedge Result X] | Row: N | New Value: $X
        ✅ 🌾 Row N | Hedge Day N: $X (date)
      Plus account matching data:
        [SESSION]      account_guess=XXX best_phase=YY
        [MATCHED EVAL] eval_idx=N account=XXXX phase=YY
        [FA PRE-COMPUTE] / [FA WRITE]
        MATCHED: MT5 Account X -> Dashboard Account Y
        📂 {firm}  └── 👤 Dashboard Account  └── 🏷️ Phase
        Source ID(s): ...
      Plus financial totals:
        mt5_account.balance / total_deposits / total_withdrawals
        Stats calculated: balance, deposits, withdrawals, actual_hedging
        FINAL DATA TO SAVE: hedging_review values
  3.  MERGES all pushes per client (not just latest) — keeps the most
      recent value for every (row, column) pair across all pushes
  4.  Applies merged data to the database
  5.  Creates a clean reconstructed backup database
  6.  Compares backup vs main DB to verify:
        - All pre-March-25 data is identical
        - Missing week data is present in the backup

Run:   python3 _reconstruct_from_logs_v2.py           (dry run)
Apply: python3 _reconstruct_from_logs_v2.py --apply    (writes to DB + backup)
"""
import os, sys, gzip, re, json, sqlite3, shutil
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
BACKUP_DIR = os.path.expanduser('~/MT5Dashboard/dashboard/')

# All error logs covering the missing week (chronological order)
ERROR_LOGS = [
    ('/var/log/www.tradeopss.com.error.log.8.gz', 'Mar 25-26'),
    ('/var/log/www.tradeopss.com.error.log.7.gz', 'Mar 26-27'),
    ('/var/log/www.tradeopss.com.error.log.6.gz', 'Mar 27-28'),
    ('/var/log/www.tradeopss.com.error.log.5.gz', 'Mar 28-29'),
    ('/var/log/www.tradeopss.com.error.log.4.gz', 'Mar 29-30'),
    ('/var/log/www.tradeopss.com.error.log.3.gz', 'Mar 30-31'),
    ('/var/log/www.tradeopss.com.error.log.1',    'Mar 31-Apr 2'),
]

CUTOFF_DATE = '2026-03-25'  # Data on or before this should be identical


def open_log(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', errors='replace')
    return open(path, 'r', errors='replace')


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: PARSE ALL LOGS
# ═══════════════════════════════════════════════════════════════════════

def parse_all_logs():
    """
    Parse every error log and extract ALL push events with full detail.

    Returns
    -------
    all_pushes : {client_id: [push_event, ...]}
        Each push_event dict has: timestamp, deal_count, balance, eval_count,
        hedge_writes, farming_writes, sessions, eval_matches, fa_accounts,
        mt5_balance/deposits/withdrawals, stats_*, hr_*, account_summary,
        received_groups, received_deals, acct_total_deposits_final,
        aggregated_groups_final
    account_maps : {client_id: {eval_idx: {account, phase, num}}}
        Cumulative eval-to-account mapping across ALL pushes
    mt5_mappings : [(mt5_account, dashboard_account, timestamp)]
    farming_accounts : {client_id: {account: {days, dates}}}
    session_accounts : {client_id: set(account_guess)}
    firm_map : {client_id: {account: firm}}
    source_id_map : {client_id: {account: set(source_ids)}}
    """
    all_pushes = defaultdict(list)
    account_maps = defaultdict(lambda: defaultdict(dict))
    mt5_mappings = []
    farming_accounts = defaultdict(lambda: defaultdict(dict))
    session_accounts = defaultdict(set)
    firm_map = defaultdict(dict)           # client -> account -> firm
    source_id_map = defaultdict(lambda: defaultdict(set))  # client -> account -> {source IDs}

    # ── Primary reconstruction patterns (cell writes) ──
    RE_PUSH     = re.compile(r'📥 Push for (.+?): (\d+) deals, balance=([\d.]+), (\d+) evaluations')
    RE_HEDGE    = re.compile(r'✅ Matched session \(Start .+?\) -> Column: \[(.+?)\] \| Row: (\d+) \| New Value: \$([\d.,+-]+)')
    RE_FARM     = re.compile(r'✅ 🌾 Row (\d+) \| Hedge Day (\d+): \$([\d.,+-]+) \((\d{4}-\d{2}-\d{2})\)')

    # ── MT5 account values (after push summary) ──
    RE_MT5_BAL  = re.compile(r'mt5_account\.balance: ([\d.,+-]+)')
    RE_MT5_DEP  = re.compile(r'mt5_account\.total_deposits: ([\d.,+-]+)')
    RE_MT5_WD   = re.compile(r'mt5_account\.total_withdrawals: ([\d.,+-]+)')

    # ── Stats calculated block ──
    RE_STATS_BAL   = re.compile(r'Current balance: \$([\d.,+-]+)')
    RE_STATS_DEP   = re.compile(r'Total deposits: \$([\d.,+-]+)')
    RE_STATS_WD    = re.compile(r'Total withdrawals: \$([\d.,+-]+)')
    RE_STATS_HEDGE = re.compile(r'Actual hedging: \$([\d.,+-]+)')

    # ── FINAL DATA TO SAVE block ──
    RE_FINAL       = re.compile(r'FINAL DATA TO SAVE for (.+?):')
    RE_HR_DEP      = re.compile(r'hedging_review\.total_deposits: \$([\d.,+-]+)')
    RE_HR_WD       = re.compile(r'hedging_review\.total_withdrawals: \$([\d.,+-]+)')
    RE_HR_BAL      = re.compile(r'hedging_review\.current_balance: \$([\d.,+-]+)')
    RE_ACCT_DEP_FINAL = re.compile(r'account\.total_deposits: \$([\d.,+-]+)')
    RE_AGG_FINAL   = re.compile(r'aggregated_by_comment: (\d+) groups')

    # ── Account number patterns ──
    RE_SESSION = re.compile(
        r'\[SESSION\] account_guess=(\S+) best_phase=(\S+) best_num=(\S+) '
        r'start=(\S+ \S+) end=(\S+ \S+) profit=([\d.+-]+)'
    )
    RE_MATCHED_EVAL = re.compile(
        r'\[MATCHED EVAL\] eval_idx=(\d+) account=(\S+) phase=(\S+) num=(\S+) drift=(\S+)'
    )
    RE_FA_PRE = re.compile(
        r"\[FA PRE-COMPUTE\] account=(\S+) farming_days=(\d+) dates=\[(.+?)\]"
    )
    RE_FA_WRITE = re.compile(
        r'\[FA WRITE\] row=(\d+) account=(\S+) total_farming_days=(\d+)'
    )
    RE_MT5_MATCH = re.compile(
        r'MATCHED: MT5 Account (\S+) -> Dashboard Account (\S+)'
    )

    # ── Account detail summary patterns ──
    RE_FIRM = re.compile(r'📂 (.+?) \((\d+) trades?\)')
    RE_DASH_ACCT = re.compile(r'👤 Dashboard Account: (\S+) \((\d+) trades?\)')
    RE_PHASE_ROW = re.compile(r'🏷️\s*Phase (\S+) -> \[(.+?)\] \(Row #(\d+)\)')
    RE_SOURCE_ID = re.compile(r'Source ID\(s\): (.+)')
    RE_ACCT_SUMMARY = re.compile(
        r'✅ (\S+) \((\S+)\) _(\w+?)(\d*) → \[(.+?)\] = \$([\d.,+-]+)'
    )

    # ── Metadata patterns ──
    RE_RECEIVED  = re.compile(r'📋 Received (\d+) aggregated groups, (\d+) raw deals')
    RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')

    for log_path, date_range in ERROR_LOGS:
        if not os.path.exists(log_path):
            print(f"  SKIP: {log_path} (not found)")
            continue

        size_mb = os.path.getsize(log_path) / 1024 / 1024
        print(f"  Parsing {os.path.basename(log_path)} ({date_range}, {size_mb:.1f}MB)...")

        # Pending buffers — collected between pushes, flushed on 📥 Push line
        pending_hedge_writes = []
        pending_farming_writes = []
        pending_sessions = []
        pending_eval_matches = []
        pending_fa_accounts = {}
        pending_acct_summaries = []
        pending_source_ids = {}          # account -> set of source IDs
        pending_firm = None              # current firm from 📂 line
        pending_dash_acct = None         # current dashboard account from 👤 line
        pending_received_groups = 0
        pending_received_deals = 0

        current_push_client = None
        current_push = None
        last_timestamp = None
        lines_processed = 0
        push_count = 0

        try:
            f = open_log(log_path)
            for line in f:
                lines_processed += 1
                line = line.strip()

                ts_match = RE_TIMESTAMP.match(line)
                if ts_match:
                    last_timestamp = ts_match.group(1)

                # ── Hedge result writes ──
                m = RE_HEDGE.search(line)
                if m:
                    col, row, val = m.group(1), int(m.group(2)), float(m.group(3).replace(',', ''))
                    pending_hedge_writes.append((row, col, val, last_timestamp or ''))
                    continue

                # ── Farming writes ──
                m = RE_FARM.search(line)
                if m:
                    row, day = int(m.group(1)), int(m.group(2))
                    val = float(m.group(3).replace(',', ''))
                    date_str = m.group(4)
                    pending_farming_writes.append((row, day, val, date_str, last_timestamp or ''))
                    continue

                # ── Account summary (✅ account (sig) _phase → [field] = $X) ──
                m = RE_ACCT_SUMMARY.search(line)
                if m:
                    pending_acct_summaries.append({
                        'account': m.group(1), 'sig': m.group(2),
                        'phase': m.group(3), 'num': m.group(4),
                        'field': m.group(5),
                        'profit': float(m.group(6).replace(',', '')),
                    })
                    continue

                # ── Session account data ──
                m = RE_SESSION.search(line)
                if m:
                    pending_sessions.append({
                        'account_guess': m.group(1), 'phase': m.group(2),
                        'num': m.group(3), 'start': m.group(4),
                        'end': m.group(5), 'profit': float(m.group(6)),
                    })
                    continue

                # ── Eval match → account-to-row mapping ──
                m = RE_MATCHED_EVAL.search(line)
                if m:
                    pending_eval_matches.append({
                        'eval_idx': int(m.group(1)), 'account': m.group(2),
                        'phase': m.group(3), 'num': m.group(4),
                        'drift': m.group(5),
                    })
                    continue

                # ── Farming pre-compute ──
                m = RE_FA_PRE.search(line)
                if m:
                    acct = m.group(1)
                    days = int(m.group(2))
                    dates = [d.strip().strip("'\"") for d in m.group(3).split(',')]
                    pending_fa_accounts[acct] = {'days': days, 'dates': dates}
                    continue

                # ── FA WRITE detail ──
                m = RE_FA_WRITE.search(line)
                if m:
                    # Captures row, account, total_farming_days — confirms farming writes
                    pass  # farming writes already captured by ✅ 🌾 line
                    continue

                # ── MT5 account mapping ──
                m = RE_MT5_MATCH.search(line)
                if m:
                    mt5_mappings.append((m.group(1), m.group(2), last_timestamp or ''))
                    continue

                # ── Firm info (📂) ──
                m = RE_FIRM.search(line)
                if m:
                    pending_firm = m.group(1)
                    continue

                # ── Dashboard account detail (👤) ──
                m = RE_DASH_ACCT.search(line)
                if m:
                    pending_dash_acct = m.group(1)
                    continue

                # ── Phase/Row detail (🏷️) — ignored, already captured from match ──

                # ── Source IDs ──
                m = RE_SOURCE_ID.search(line)
                if m:
                    ids = [s.strip() for s in m.group(1).split(',')]
                    if pending_dash_acct:
                        if pending_dash_acct not in pending_source_ids:
                            pending_source_ids[pending_dash_acct] = set()
                        pending_source_ids[pending_dash_acct].update(ids)
                    continue

                # ── Received line — signals a NEW push context starting ──
                m = RE_RECEIVED.search(line)
                if m:
                    pending_received_groups = int(m.group(1))
                    pending_received_deals = int(m.group(2))
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    pending_acct_summaries = []
                    pending_source_ids = {}
                    pending_firm = None
                    pending_dash_acct = None
                    continue

                # ── Push summary → flush ALL pending data to this client ──
                m = RE_PUSH.search(line)
                if m:
                    client_id = m.group(1)
                    push_count += 1
                    current_push_client = client_id
                    current_push = {
                        'timestamp': last_timestamp or '',
                        'deal_count': int(m.group(2)),
                        'balance': float(m.group(3)),
                        'eval_count': int(m.group(4)),
                        # Cell writes
                        'hedge_writes': list(pending_hedge_writes),
                        'farming_writes': list(pending_farming_writes),
                        'acct_summaries': list(pending_acct_summaries),
                        # Account matching data
                        'sessions': list(pending_sessions),
                        'eval_matches': list(pending_eval_matches),
                        'fa_accounts': dict(pending_fa_accounts),
                        'source_ids': {k: list(v) for k, v in pending_source_ids.items()},
                        # Metadata
                        'received_groups': pending_received_groups,
                        'received_deals': pending_received_deals,
                        # MT5 values (filled after push summary)
                        'mt5_balance': None, 'mt5_deposits': None, 'mt5_withdrawals': None,
                        # Stats (filled after push summary)
                        'stats_balance': None, 'stats_deposits': None,
                        'stats_withdrawals': None, 'stats_hedging': None,
                        # Hedging review (filled from FINAL block)
                        'hr_deposits': None, 'hr_withdrawals': None, 'hr_balance': None,
                        # Additional FINAL block values
                        'acct_total_deposits_final': None,
                        'aggregated_groups_final': None,
                    }
                    all_pushes[client_id].append(current_push)

                    # Accumulate global maps
                    for em in pending_eval_matches:
                        account_maps[client_id][em['eval_idx']] = {
                            'account': em['account'], 'phase': em['phase'], 'num': em['num'],
                        }
                    for s in pending_sessions:
                        session_accounts[client_id].add(s['account_guess'])
                    for acct, info in pending_fa_accounts.items():
                        farming_accounts[client_id][acct] = info
                    # Firm data from account detail section
                    for acct_sum in pending_acct_summaries:
                        if pending_firm:
                            firm_map[client_id][acct_sum['account']] = pending_firm
                    for acct, ids in pending_source_ids.items():
                        source_id_map[client_id][acct].update(ids)

                    # Clear pending buffers
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    pending_acct_summaries = []
                    pending_source_ids = {}
                    pending_firm = None
                    pending_dash_acct = None
                    pending_received_groups = 0
                    pending_received_deals = 0
                    continue

                # ── POST-PUSH DATA (mt5, stats, FINAL block) ──
                if current_push:
                    m = RE_MT5_BAL.search(line)
                    if m and current_push['mt5_balance'] is None:
                        current_push['mt5_balance'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_MT5_DEP.search(line)
                    if m and current_push['mt5_deposits'] is None:
                        current_push['mt5_deposits'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_MT5_WD.search(line)
                    if m and current_push['mt5_withdrawals'] is None:
                        current_push['mt5_withdrawals'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_STATS_BAL.search(line)
                    if m:
                        current_push['stats_balance'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_STATS_DEP.search(line)
                    if m:
                        current_push['stats_deposits'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_STATS_WD.search(line)
                    if m:
                        current_push['stats_withdrawals'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_STATS_HEDGE.search(line)
                    if m:
                        current_push['stats_hedging'] = float(m.group(1).replace(',', ''))
                        continue

                # ── FINAL DATA TO SAVE block ──
                m = RE_FINAL.search(line)
                if m:
                    final_client = m.group(1)
                    if final_client in all_pushes and all_pushes[final_client]:
                        current_push_client = final_client
                        current_push = all_pushes[final_client][-1]
                    continue

                if current_push:
                    m = RE_HR_DEP.search(line)
                    if m:
                        current_push['hr_deposits'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_HR_WD.search(line)
                    if m:
                        current_push['hr_withdrawals'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_HR_BAL.search(line)
                    if m:
                        current_push['hr_balance'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_ACCT_DEP_FINAL.search(line)
                    if m:
                        current_push['acct_total_deposits_final'] = float(m.group(1).replace(',', ''))
                        continue
                    m = RE_AGG_FINAL.search(line)
                    if m:
                        current_push['aggregated_groups_final'] = int(m.group(1))
                        continue

                # ── Push completed → reset context ──
                if '[REQUEST] POST /api/client/push -> 200' in line:
                    current_push = None
                    current_push_client = None

            f.close()
            print(f"    → {lines_processed:,} lines, {push_count} push events found")

        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback; traceback.print_exc()

    return (all_pushes, account_maps, mt5_mappings, farming_accounts,
            session_accounts, firm_map, source_id_map)


def parse_api_activity(all_pushes):
    """
    Second pass over error logs: extract ALL [REQUEST] lines for update_data,
    notes, login, and auth endpoints to identify non-push client activity.

    Also extract any client-identifying context near update_data requests.

    Returns:
      update_data_requests: [(timestamp, status_code, duration_ms)]
      login_events: [(timestamp, email_or_path)]
      api_summary: {endpoint: count}
    """
    update_data_requests = []
    login_events = []
    api_summary = defaultdict(int)

    RE_REQUEST = re.compile(
        r'\[REQUEST\] (\w+) (.+?) -> (\d+) \(([\d.]+)ms\)'
    )
    RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')

    # Patterns that identify clients near update_data calls
    RE_WIPE_BLOCKED = re.compile(
        r'WIPE_BLOCKED.*?(\S+): incoming (\d+) evals vs existing (\d+)'
    )

    for log_path, date_range in ERROR_LOGS:
        if not os.path.exists(log_path):
            continue
        try:
            f = open_log(log_path)
            last_ts = None
            for line in f:
                line = line.strip()
                ts_m = RE_TIMESTAMP.match(line)
                if ts_m:
                    last_ts = ts_m.group(1)

                m = RE_REQUEST.search(line)
                if m:
                    method, path, status, dur = m.group(1), m.group(2), m.group(3), m.group(4)
                    endpoint = f"{method} {path.split('?')[0]}"
                    api_summary[endpoint] += 1

                    if '/api/update_data' in path:
                        update_data_requests.append((last_ts or '', int(status), float(dur)))
                    elif '/api/login' in path or '/api/auth/login' in path or '/api/client/auth' in path:
                        login_events.append((last_ts or '', path))

                m = RE_WIPE_BLOCKED.search(line)
                if m:
                    # This is a rare but useful signal — tells us client + eval counts
                    pass  # Captured in audit_log, but good to know it appears in error logs

            f.close()
        except Exception as e:
            print(f"    ERROR parsing API activity from {log_path}: {e}")

    return update_data_requests, login_events, api_summary


def scan_audit_log_and_history(db_path=None):
    """
    Scan the audit_log and data_history tables in the DB for surviving
    entries from the missing week (March 26 - April 1).

    The WAL truncation destroyed uncommitted data, but any entries that
    were checkpointed before the incident may survive.
    """
    target_db = db_path or DB_PATH
    if not os.path.exists(target_db):
        return {}, {}

    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row

    # Check audit_log
    audit_entries = []
    try:
        rows = conn.execute('''
            SELECT * FROM audit_log
            WHERE timestamp >= '2026-03-25' AND timestamp < '2026-04-02'
            ORDER BY timestamp
        ''').fetchall()
        audit_entries = [dict(r) for r in rows]
    except Exception as e:
        print(f"  audit_log query error: {e}")

    # Check data_history
    history_entries = []
    try:
        rows = conn.execute('''
            SELECT id, client_id, version, action, changed_by, changed_by_type,
                   change_source, change_description, created_at,
                   LENGTH(evaluations) as eval_len,
                   LENGTH(account) as acct_len,
                   LENGTH(statistics) as stats_len
            FROM data_history
            WHERE created_at >= '2026-03-25' AND created_at < '2026-04-02'
            ORDER BY created_at
        ''').fetchall()
        history_entries = [dict(r) for r in rows]
    except Exception as e:
        print(f"  data_history query error: {e}")

    # Also get total counts
    try:
        audit_total = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    except:
        audit_total = '?'
    try:
        history_total = conn.execute('SELECT COUNT(*) FROM data_history').fetchone()[0]
    except:
        history_total = '?'

    conn.close()

    return {
        'audit_entries': audit_entries,
        'audit_total': audit_total,
        'history_entries': history_entries,
        'history_total': history_total,
    }


def report_non_push_clients(all_pushes, db_path=None):
    """
    Find ALL clients in the DB and identify which ones had NO push events
    during the missing week. For those clients, report their current state
    so we know what may need manual recovery.
    """
    target_db = db_path or DB_PATH
    if not os.path.exists(target_db):
        return []

    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT client_id, evaluations, account, identity, last_updated,
               hedge_accounts, prop_accounts, vps_accounts
        FROM clients_data ORDER BY client_id
    ''').fetchall()
    conn.close()

    pushed_clients = set(all_pushes.keys())
    non_push_clients = []

    for row in rows:
        cid = row['client_id']
        if cid in pushed_clients:
            continue

        # This client had NO push during the week — report their state
        evaluations = json.loads(row['evaluations'] or '[]')
        account = json.loads(row['account'] or '{}')
        identity = json.loads(row['identity'] or '{}')
        hedge_accts = json.loads(row['hedge_accounts'] or '[]')
        prop_accts = json.loads(row['prop_accounts'] or '[]')
        vps_accts = json.loads(row['vps_accounts'] or '[]')
        last_updated = row['last_updated'] or ''

        # Determine stage from evaluations
        eval_count = len(evaluations)
        funded_count = sum(1 for e in evaluations
                          if (e.get('Funded Status', '') or '').strip().lower() in ('yes', 'funded', 'true'))
        active_count = sum(1 for e in evaluations
                           if e.get('Phase 1 Status', ''))

        # Extract account numbers from evaluations
        account_numbers = set()
        for ev in evaluations:
            an = ev.get('Account Number', '')
            if an:
                account_numbers.add(an)

        non_push_clients.append({
            'client_id': cid,
            'last_updated': last_updated,
            'eval_count': eval_count,
            'funded_count': funded_count,
            'active_count': active_count,
            'account_numbers': sorted(account_numbers),
            'hedge_accounts': len(hedge_accts),
            'prop_accounts': len(prop_accts),
            'vps_accounts': len(vps_accts),
            'identity_email': identity.get('email', ''),
            'balance': account.get('balance', 0),
            'has_identity': bool(identity.get('email')),
        })

    return non_push_clients


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: MERGE ALL PUSHES PER CLIENT
# ═══════════════════════════════════════════════════════════════════════

def get_merged_pushes(all_pushes):
    """
    For each client, merge ALL pushes across the entire week.

    Different pushes may write to different (row, column) combinations because
    different trading sessions match different evaluations. We keep the LATEST
    value for every (row, column) and use the latest push for MT5/stats/HR.

    Returns {client_id: merged_push_dict}
    """
    merged = {}

    for client_id, pushes in all_pushes.items():
        sorted_pushes = sorted(pushes, key=lambda p: p['timestamp'])

        # Merge hedge writes: (row, col) → (val, timestamp)
        hedge_map = {}
        for push in sorted_pushes:
            for row, col, val, ts in push['hedge_writes']:
                key = (row, col)
                if key not in hedge_map or ts >= hedge_map[key][1]:
                    hedge_map[key] = (val, ts)

        # Merge farming writes: (row, day) → (val, date_str, timestamp)
        farm_map = {}
        for push in sorted_pushes:
            for row, day, val, date_str, ts in push['farming_writes']:
                key = (row, day)
                if key not in farm_map or ts >= farm_map[key][2]:
                    farm_map[key] = (val, date_str, ts)

        # Merge eval matches: eval_idx → latest info
        merged_eval_matches = {}
        for push in sorted_pushes:
            for em in push.get('eval_matches', []):
                merged_eval_matches[em['eval_idx']] = em

        # Merge sessions (cumulative set)
        all_sessions = []
        for push in sorted_pushes:
            all_sessions.extend(push.get('sessions', []))

        # Merge account summaries (cumulative set)
        all_acct_summaries = []
        for push in sorted_pushes:
            all_acct_summaries.extend(push.get('acct_summaries', []))

        # Latest push for scalar values
        latest = sorted_pushes[-1]

        merged[client_id] = {
            'timestamp': latest['timestamp'],
            'deal_count': latest['deal_count'],
            'balance': latest['balance'],
            'eval_count': latest['eval_count'],
            'total_pushes': len(pushes),
            # Merged cell writes — converted back to list format
            'hedge_writes': [(r, c, v) for (r, c), (v, _ts) in sorted(hedge_map.items())],
            'farming_writes': [(r, d, v, ds) for (r, d), (v, ds, _ts) in sorted(farm_map.items())],
            # Merged account data
            'eval_matches': list(merged_eval_matches.values()),
            'sessions': all_sessions,
            'acct_summaries': all_acct_summaries,
            # Latest scalar values
            'mt5_balance': latest['mt5_balance'],
            'mt5_deposits': latest['mt5_deposits'],
            'mt5_withdrawals': latest['mt5_withdrawals'],
            'stats_balance': latest['stats_balance'],
            'stats_deposits': latest['stats_deposits'],
            'stats_withdrawals': latest['stats_withdrawals'],
            'stats_hedging': latest['stats_hedging'],
            'hr_deposits': latest['hr_deposits'],
            'hr_withdrawals': latest['hr_withdrawals'],
            'hr_balance': latest['hr_balance'],
            'acct_total_deposits_final': latest.get('acct_total_deposits_final'),
            'aggregated_groups_final': latest.get('aggregated_groups_final'),
        }

        # If latest push has None for MT5/stats values, scan backwards
        for field in ('mt5_balance', 'mt5_deposits', 'mt5_withdrawals',
                      'hr_deposits', 'hr_withdrawals', 'hr_balance',
                      'stats_balance', 'stats_deposits', 'stats_withdrawals',
                      'stats_hedging'):
            if merged[client_id][field] is None:
                for p in reversed(sorted_pushes[:-1]):
                    if p.get(field) is not None:
                        merged[client_id][field] = p[field]
                        break

    return merged


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: APPLY TO DATABASE
# ═══════════════════════════════════════════════════════════════════════

def apply_to_database(merged_pushes, account_maps, session_accounts,
                      db_path=None, dry_run=True):
    """
    Apply ALL merged push data to the database.

    For each client:
    1. Load current evaluations from DB
    2. Apply ALL merged hedge result writes (every (row, col) pair ever written)
    3. Apply ALL merged farming writes
    4. Update account dict with MT5 values
    5. Update statistics.hedging_review with logged values
    6. Reconstruct Account Number field in evaluations from [MATCHED EVAL] data
    7. Save back to DB
    """
    target_db = db_path or DB_PATH
    if not os.path.exists(target_db):
        print(f"ERROR: Database not found at {target_db}")
        return 0, 0, 0

    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row

    updated = 0
    skipped = 0
    errors = 0

    for client_id, push in sorted(merged_pushes.items()):
        try:
            row = conn.execute(
                'SELECT client_id, evaluations, account, statistics, last_updated '
                'FROM clients_data WHERE client_id = ?',
                (client_id,)
            ).fetchone()

            if not row:
                print(f"  ⚠️  {client_id}: NOT in database — skipping")
                skipped += 1
                continue

            db_last = row['last_updated'] or ''
            push_ts = push['timestamp']

            # Only update if our log data is NEWER than what's in the DB
            if db_last > push_ts:
                print(f"  ⏭️  {client_id}: DB has newer data ({db_last} > {push_ts}) — skipping")
                skipped += 1
                continue

            evaluations = json.loads(row['evaluations'] or '[]')
            account = json.loads(row['account'] or '{}')
            statistics = json.loads(row['statistics'] or '{}')
            changes = []

            # ── 1. Apply ALL merged hedge result writes ──
            hedge_ok = 0
            hedge_oor = 0
            for eval_row, column, value in push['hedge_writes']:
                if eval_row < len(evaluations):
                    old_val = evaluations[eval_row].get(column, 'N/A')
                    evaluations[eval_row][column] = f"{value:.2f}"
                    hedge_ok += 1
                    if len(changes) < 20:
                        changes.append(f"eval[{eval_row}][{column}] = {value:.2f} (was {old_val})")
                else:
                    hedge_oor += 1
            if hedge_ok:
                changes.append(f"→ {hedge_ok} hedge writes applied")
            if hedge_oor:
                changes.append(f"⚠️ {hedge_oor} hedge writes OUT OF RANGE")

            # ── 2. Apply ALL merged farming writes ──
            farm_ok = 0
            farm_oor = 0
            for eval_row, day_num, value, date_str in push['farming_writes']:
                field = f'Hedge Day {day_num}'
                date_field = f'_Hedge Day {day_num} Date'
                if eval_row < len(evaluations):
                    evaluations[eval_row][field] = f"{value:.2f}"
                    evaluations[eval_row][date_field] = date_str
                    farm_ok += 1
                    if len(changes) < 30:
                        changes.append(f"eval[{eval_row}][{field}] = {value:.2f} ({date_str})")
                else:
                    farm_oor += 1
            if farm_ok:
                changes.append(f"→ {farm_ok} farming writes applied")
            if farm_oor:
                changes.append(f"⚠️ {farm_oor} farming writes OUT OF RANGE")

            # ── 3. Update account MT5 values ──
            if push['mt5_balance'] is not None:
                old_b = account.get('balance', 'N/A')
                account['balance'] = push['mt5_balance']
                changes.append(f"account.balance = {push['mt5_balance']} (was {old_b})")
            if push['mt5_deposits'] is not None:
                old_d = account.get('total_deposits', 'N/A')
                account['total_deposits'] = push['mt5_deposits']
                changes.append(f"account.total_deposits = {push['mt5_deposits']} (was {old_d})")
            if push['mt5_withdrawals'] is not None:
                old_w = account.get('total_withdrawals', 'N/A')
                account['total_withdrawals'] = push['mt5_withdrawals']
                changes.append(f"account.total_withdrawals = {push['mt5_withdrawals']} (was {old_w})")

            # ── 4. Update hedging_review in statistics ──
            hr = statistics.get('hedging_review', {})
            hr_changed = False
            if push['hr_deposits'] is not None:
                hr['total_deposits'] = push['hr_deposits']; hr_changed = True
            if push['hr_withdrawals'] is not None:
                hr['total_withdrawals'] = push['hr_withdrawals']; hr_changed = True
            if push['hr_balance'] is not None:
                hr['current_balance'] = push['hr_balance']; hr_changed = True
            if push['stats_hedging'] is not None:
                hr['actual_hedging_results'] = push['stats_hedging']; hr_changed = True
            if hr_changed:
                statistics['hedging_review'] = hr
                changes.append(f"hedging_review updated (dep={hr.get('total_deposits')}, "
                               f"wd={hr.get('total_withdrawals')}, bal={hr.get('current_balance')}, "
                               f"hedge={hr.get('actual_hedging_results')})")

            # ── 5. Reconstruct Account Number in evaluations ──
            acct_changes = 0
            if client_id in account_maps:
                for eval_idx, info in account_maps[client_id].items():
                    if eval_idx < len(evaluations):
                        raw_acct = info['account']
                        # Find full account_guess containing this raw number
                        full_acct = raw_acct
                        if client_id in session_accounts:
                            for sa in session_accounts[client_id]:
                                if raw_acct in sa:
                                    full_acct = sa
                                    break
                        old_acct = evaluations[eval_idx].get('Account Number', '')
                        if not old_acct or old_acct != full_acct:
                            evaluations[eval_idx]['Account Number'] = full_acct
                            acct_changes += 1
            if acct_changes:
                changes.append(f"Updated {acct_changes} evaluation Account Number fields")

            # ── Print summary ──
            n_hedge = len(push['hedge_writes'])
            n_farm = len(push['farming_writes'])
            n_total_pushes = push['total_pushes']
            tag = '[DRY RUN] ' if dry_run else ''
            print(f"\n  {tag}✅ {client_id} ({push_ts}, {n_total_pushes} pushes merged):")
            print(f"     {n_hedge} hedge writes, {n_farm} farming writes, "
                  f"evals={push['eval_count']}, deals={push['deal_count']}, bal={push['balance']}")
            if changes:
                for c in changes[:25]:
                    print(f"       → {c}")
                if len(changes) > 25:
                    print(f"       ... and {len(changes) - 25} more changes")

            if not dry_run:
                conn.execute('''
                    UPDATE clients_data
                    SET evaluations = ?, account = ?, statistics = ?, last_updated = ?
                    WHERE client_id = ?
                ''', (
                    json.dumps(evaluations),
                    json.dumps(account),
                    json.dumps(statistics),
                    push_ts,
                    client_id
                ))
            updated += 1

        except Exception as e:
            print(f"  ❌ {client_id}: ERROR — {e}")
            import traceback; traceback.print_exc()
            errors += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return updated, skipped, errors


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: CREATE BACKUP DATABASE
# ═══════════════════════════════════════════════════════════════════════

def create_backup_database(merged_pushes, account_maps, session_accounts):
    """Copy current DB → apply all reconstructed data → verify integrity."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'dashboard_reconstructed_{timestamp}.db')

    print(f"\n  Creating backup database: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)

    updated, skipped, errors = apply_to_database(
        merged_pushes, account_maps, session_accounts,
        db_path=backup_path, dry_run=False
    )

    conn = sqlite3.connect(backup_path)
    try:
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    except Exception as e:
        integrity = f'ERROR: {e}'
    try:
        count = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
    except:
        count = '?'
    conn.close()

    size_mb = os.path.getsize(backup_path) / 1024 / 1024
    print(f"\n  ✅ Backup database created:")
    print(f"     Path: {backup_path}")
    print(f"     Size: {size_mb:.1f} MB")
    print(f"     Clients: {count}")
    print(f"     Integrity: {integrity}")
    print(f"     Updated: {updated}, Skipped: {skipped}, Errors: {errors}")
    return backup_path


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5: COMPARE BACKUP DB vs MAIN DB
# ═══════════════════════════════════════════════════════════════════════

ALL_COLUMNS = [
    'client_id', 'deals', 'positions', 'account', 'evaluations',
    'statistics', 'dropdown_options', 'identity', 'last_updated',
    'hedge_accounts', 'prop_accounts', 'vps_accounts',
    'payment_info', 'payment_address',
]

# Columns that the reconstruction modifies
MODIFIED_COLUMNS = {'evaluations', 'account', 'statistics', 'last_updated'}

# Columns that should be IDENTICAL (not touched by reconstruction)
PRESERVED_COLUMNS = {
    'deals', 'positions', 'dropdown_options', 'identity',
    'hedge_accounts', 'prop_accounts', 'vps_accounts',
    'payment_info', 'payment_address',
}


def _json_equal(a, b):
    """Compare two JSON-stringified values for equality."""
    try:
        return json.loads(a or '{}') == json.loads(b or '{}')
    except:
        return a == b


def _deep_diff_evaluations(main_evals, backup_evals):
    """
    Deep-diff two evaluations arrays.
    Returns list of (row_idx, field, main_val, backup_val) tuples.
    """
    diffs = []
    max_len = max(len(main_evals), len(backup_evals))
    for i in range(max_len):
        if i >= len(main_evals):
            diffs.append((i, '<ENTIRE ROW>', '<missing>', '<present>'))
            continue
        if i >= len(backup_evals):
            diffs.append((i, '<ENTIRE ROW>', '<present>', '<missing>'))
            continue
        m_row = main_evals[i]
        b_row = backup_evals[i]
        all_keys = set(m_row.keys()) | set(b_row.keys())
        for key in sorted(all_keys):
            mv = m_row.get(key, '')
            bv = b_row.get(key, '')
            if str(mv) != str(bv):
                diffs.append((i, key, mv, bv))
    return diffs


def compare_databases(main_db, backup_db, merged_pushes):
    """
    Compare the main DB and backup DB client by client.

    Reports:
    1. Clients identical in both (base data verified)
    2. Clients with reconstructed data in backup (missing week recovered)
    3. Any unexpected discrepancies in PRESERVED columns
    """
    print(f"\n{'='*80}")
    print("COMPARING MAIN DB vs RECONSTRUCTED BACKUP DB")
    print(f"{'='*80}\n")
    print(f"  Main DB:   {main_db}")
    print(f"  Backup DB: {backup_db}\n")

    conn_main = sqlite3.connect(main_db)
    conn_main.row_factory = sqlite3.Row
    conn_backup = sqlite3.connect(backup_db)
    conn_backup.row_factory = sqlite3.Row

    # Load all clients from both
    main_rows = {r['client_id']: dict(r) for r in
                 conn_main.execute('SELECT * FROM clients_data ORDER BY client_id')}
    backup_rows = {r['client_id']: dict(r) for r in
                   conn_backup.execute('SELECT * FROM clients_data ORDER BY client_id')}

    conn_main.close()
    conn_backup.close()

    main_only = set(main_rows.keys()) - set(backup_rows.keys())
    backup_only = set(backup_rows.keys()) - set(main_rows.keys())
    common = set(main_rows.keys()) & set(backup_rows.keys())

    if main_only:
        print(f"  ⚠️  Clients ONLY in main DB ({len(main_only)}): {sorted(main_only)}")
    if backup_only:
        print(f"  ⚠️  Clients ONLY in backup DB ({len(backup_only)}): {sorted(backup_only)}")

    identical_clients = 0
    reconstructed_clients = 0
    preserved_violations = 0
    total_eval_diffs = 0
    total_account_diffs = 0
    total_stats_diffs = 0
    client_details = []

    for client_id in sorted(common):
        mr = main_rows[client_id]
        br = backup_rows[client_id]

        # Check PRESERVED columns (should be identical)
        preserved_ok = True
        for col in PRESERVED_COLUMNS:
            mv = mr.get(col, '')
            bv = br.get(col, '')
            if not _json_equal(mv, bv):
                preserved_ok = False
                preserved_violations += 1
                print(f"  🚨 {client_id}: PRESERVED column '{col}' DIFFERS!")
                # Show first 200 chars of diff
                mv_short = str(mv)[:200]
                bv_short = str(bv)[:200]
                print(f"      Main:   {mv_short}")
                print(f"      Backup: {bv_short}")

        # Check MODIFIED columns
        evals_differ = not _json_equal(mr.get('evaluations', ''), br.get('evaluations', ''))
        account_differs = not _json_equal(mr.get('account', ''), br.get('account', ''))
        stats_differ = not _json_equal(mr.get('statistics', ''), br.get('statistics', ''))
        ts_differs = mr.get('last_updated', '') != br.get('last_updated', '')

        any_modified = evals_differ or account_differs or stats_differ

        if not any_modified and preserved_ok:
            identical_clients += 1
            continue

        reconstructed_clients += 1

        # Detailed evaluation diff
        eval_diffs = []
        if evals_differ:
            try:
                m_evals = json.loads(mr.get('evaluations', '[]') or '[]')
                b_evals = json.loads(br.get('evaluations', '[]') or '[]')
                eval_diffs = _deep_diff_evaluations(m_evals, b_evals)
                total_eval_diffs += len(eval_diffs)
            except:
                eval_diffs = [(-1, '<parse error>', '', '')]

        # Detailed account diff
        acct_diffs = []
        if account_differs:
            try:
                m_acct = json.loads(mr.get('account', '{}') or '{}')
                b_acct = json.loads(br.get('account', '{}') or '{}')
                all_keys = set(m_acct.keys()) | set(b_acct.keys())
                for k in sorted(all_keys):
                    if str(m_acct.get(k, '')) != str(b_acct.get(k, '')):
                        acct_diffs.append((k, m_acct.get(k, ''), b_acct.get(k, '')))
                total_account_diffs += len(acct_diffs)
            except:
                acct_diffs = [('<parse error>', '', '')]

        # Stats diff (just count)
        if stats_differ:
            total_stats_diffs += 1

        # Collect for report
        m_ts = mr.get('last_updated', '')
        b_ts = br.get('last_updated', '')

        detail = {
            'client_id': client_id,
            'main_ts': m_ts,
            'backup_ts': b_ts,
            'eval_diff_count': len(eval_diffs),
            'eval_diffs': eval_diffs[:50],  # Cap for display
            'acct_diffs': acct_diffs,
            'stats_differ': stats_differ,
            'preserved_ok': preserved_ok,
        }
        client_details.append(detail)

    # ── Print detailed report ──
    print(f"\n{'─'*80}")
    print(f"COMPARISON SUMMARY")
    print(f"{'─'*80}")
    print(f"  Total clients in both DBs: {len(common)}")
    print(f"  Identical (no changes):    {identical_clients}")
    print(f"  Reconstructed (changed):   {reconstructed_clients}")
    print(f"  Preserved column errors:   {preserved_violations}")
    print(f"  Total eval cell diffs:     {total_eval_diffs}")
    print(f"  Total account field diffs: {total_account_diffs}")
    print(f"  Clients with stats diffs:  {total_stats_diffs}")

    if preserved_violations == 0:
        print(f"\n  ✅ ALL PRESERVED COLUMNS ARE IDENTICAL — base data integrity VERIFIED")
    else:
        print(f"\n  🚨 {preserved_violations} PRESERVED COLUMN VIOLATIONS — investigate!")

    # ── Per-client details for reconstructed clients ──
    if client_details:
        print(f"\n{'─'*80}")
        print(f"RECONSTRUCTED CLIENT DETAILS ({len(client_details)} clients)")
        print(f"{'─'*80}")

        for d in client_details:
            cid = d['client_id']
            was_pushed = cid in merged_pushes
            push_info = f", {merged_pushes[cid]['total_pushes']} pushes" if was_pushed else ""
            print(f"\n  📝 {cid} (main: {d['main_ts']} → backup: {d['backup_ts']}{push_info})")

            if not d['preserved_ok']:
                print(f"     🚨 PRESERVED COLUMNS DIFFER!")

            if d['eval_diffs']:
                # Group by type: Hedge Result vs Hedge Day vs Account Number vs other
                hr_diffs = [e for e in d['eval_diffs'] if 'Hedge Result' in str(e[1])]
                hd_diffs = [e for e in d['eval_diffs'] if 'Hedge Day' in str(e[1]) and not str(e[1]).startswith('_')]
                an_diffs = [e for e in d['eval_diffs'] if 'Account Number' in str(e[1])]
                other_diffs = [e for e in d['eval_diffs']
                               if e not in hr_diffs and e not in hd_diffs and e not in an_diffs]

                if hr_diffs:
                    print(f"     Hedge Results changed ({len(hr_diffs)}):")
                    for row_idx, field, mv, bv in hr_diffs[:10]:
                        print(f"       Row {row_idx}: {field}: {mv} → {bv}")
                    if len(hr_diffs) > 10:
                        print(f"       ... and {len(hr_diffs) - 10} more")

                if hd_diffs:
                    print(f"     Farming Days changed ({len(hd_diffs)}):")
                    for row_idx, field, mv, bv in hd_diffs[:10]:
                        print(f"       Row {row_idx}: {field}: {mv} → {bv}")
                    if len(hd_diffs) > 10:
                        print(f"       ... and {len(hd_diffs) - 10} more")

                if an_diffs:
                    print(f"     Account Numbers set ({len(an_diffs)}):")
                    for row_idx, field, mv, bv in an_diffs[:10]:
                        print(f"       Row {row_idx}: '{mv}' → '{bv}'")

                if other_diffs:
                    print(f"     Other eval fields changed ({len(other_diffs)}):")
                    for row_idx, field, mv, bv in other_diffs[:5]:
                        print(f"       Row {row_idx}: {field}: {mv} → {bv}")

            if d['acct_diffs']:
                print(f"     Account values changed ({len(d['acct_diffs'])}):")
                for k, mv, bv in d['acct_diffs']:
                    print(f"       {k}: {mv} → {bv}")

            if d['stats_differ']:
                print(f"     Statistics/hedging_review: UPDATED")

    # ── Verify missing week data is present ──
    print(f"\n{'─'*80}")
    print("MISSING WEEK VERIFICATION (March 26 - April 1)")
    print(f"{'─'*80}")

    clients_with_week_data = 0
    clients_with_hedge_data = 0
    clients_with_farm_data = 0
    total_hedge_cells = 0
    total_farm_cells = 0

    for d in client_details:
        has_hedge = any('Hedge Result' in str(e[1]) for e in d.get('eval_diffs', []))
        has_farm = any('Hedge Day' in str(e[1]) and not str(e[1]).startswith('_')
                       for e in d.get('eval_diffs', []))
        if has_hedge or has_farm:
            clients_with_week_data += 1
        if has_hedge:
            clients_with_hedge_data += 1
            total_hedge_cells += sum(1 for e in d['eval_diffs'] if 'Hedge Result' in str(e[1]))
        if has_farm:
            clients_with_farm_data += 1
            total_farm_cells += sum(1 for e in d['eval_diffs']
                                    if 'Hedge Day' in str(e[1]) and not str(e[1]).startswith('_'))

    print(f"  Clients with recovered week data: {clients_with_week_data}")
    print(f"    With hedge result data: {clients_with_hedge_data} ({total_hedge_cells} cells)")
    print(f"    With farming day data:  {clients_with_farm_data} ({total_farm_cells} cells)")

    if clients_with_week_data > 0:
        print(f"\n  ✅ Missing week data IS PRESENT in the backup database")
    else:
        print(f"\n  ⚠️ No missing week data found — check if all clients had pushes during Mar 26-Apr 1")

    return {
        'identical': identical_clients,
        'reconstructed': reconstructed_clients,
        'preserved_violations': preserved_violations,
        'eval_diffs': total_eval_diffs,
        'account_diffs': total_account_diffs,
        'stats_diffs': total_stats_diffs,
    }


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 100)
    print("RECONSTRUCT CLIENT DATA FROM SERVER LOGS  (V2 — THOROUGH)")
    print(f"Time: {datetime.now()}")
    print("=" * 100)

    # ── PHASE 1: Parse all error logs ──
    print(f"\n{'='*80}")
    print("PHASE 1: PARSING ALL ERROR LOGS")
    print(f"{'='*80}\n")

    (all_pushes, account_maps, mt5_mappings, farming_accounts,
     session_accounts, firm_map, source_id_map) = parse_all_logs()

    total_events = sum(len(v) for v in all_pushes.values())
    total_eval_mappings = sum(len(v) for v in account_maps.values())
    total_farm_accts = sum(len(v) for v in farming_accounts.values())
    total_session_accts = sum(len(v) for v in session_accounts.values())
    total_firms = sum(len(v) for v in firm_map.values())
    total_source_ids = sum(len(ids) for accts in source_id_map.values() for ids in accts.values())

    # Count ALL hedge/farm writes across all pushes (not just latest)
    total_all_hedge = sum(len(w) for pushes in all_pushes.values() for p in pushes for w in [p['hedge_writes']])
    total_all_farm = sum(len(w) for pushes in all_pushes.values() for p in pushes for w in [p['farming_writes']])

    print(f"\n  TOTAL EXTRACTED:")
    print(f"    Unique clients:            {len(all_pushes)}")
    print(f"    Push events:               {total_events}")
    print(f"    Hedge writes (all pushes): {total_all_hedge}")
    print(f"    Farm writes (all pushes):  {total_all_farm}")
    print(f"    Eval→account mappings:     {total_eval_mappings}")
    print(f"    MT5 account mappings:      {len(mt5_mappings)}")
    print(f"    Farming accounts:          {total_farm_accts}")
    print(f"    Session accounts:          {total_session_accts}")
    print(f"    Firm mappings:             {total_firms}")
    print(f"    Source IDs:                {total_source_ids}")

    # ── PHASE 2: Merge all pushes per client ──
    print(f"\n{'='*80}")
    print("PHASE 2: MERGING ALL PUSHES PER CLIENT")
    print(f"{'='*80}\n")

    merged = get_merged_pushes(all_pushes)

    for client_id in sorted(merged.keys()):
        m = merged[client_id]
        n_pushes = m['total_pushes']
        n_hedge = len(m['hedge_writes'])
        n_farm = len(m['farming_writes'])
        n_accts = len(session_accounts.get(client_id, set()))
        print(f"  {client_id:<30} {n_pushes:>3} pushes merged | {m['timestamp']} | "
              f"deals={m['deal_count']}, bal={m['balance']}, evals={m['eval_count']} | "
              f"hedge={n_hedge}, farm={n_farm}, accts={n_accts}")

    total_merged_hedge = sum(len(m['hedge_writes']) for m in merged.values())
    total_merged_farm = sum(len(m['farming_writes']) for m in merged.values())
    print(f"\n  MERGED SUMMARY:")
    print(f"    Clients: {len(merged)}")
    print(f"    Unique (row,col) hedge writes: {total_merged_hedge}")
    print(f"    Unique (row,day) farming writes: {total_merged_farm}")

    all_ts = [m['timestamp'] for m in merged.values() if m['timestamp']]
    if all_ts:
        print(f"    Date range: {min(all_ts)} → {max(all_ts)}")

    # ── PHASE 3: Account number report ──
    print(f"\n{'='*80}")
    print("PHASE 3: ACCOUNT NUMBERS RECOVERED FROM LOGS")
    print(f"{'='*80}\n")

    for client_id in sorted(session_accounts.keys()):
        accts = sorted(session_accounts[client_id])
        farm_accts = list(farming_accounts.get(client_id, {}).keys())
        firms = firm_map.get(client_id, {})
        sources = source_id_map.get(client_id, {})

        print(f"  {client_id}:")
        print(f"    Session accounts ({len(accts)}): {', '.join(accts[:20])}")
        if farm_accts:
            print(f"    Farming accounts ({len(farm_accts)}): {', '.join(farm_accts[:10])}")
        if firms:
            unique_firms = set(firms.values())
            print(f"    Firms: {', '.join(sorted(unique_firms))}")
        if sources:
            all_src = set()
            for ids in sources.values():
                all_src.update(ids)
            print(f"    Source IDs: {', '.join(sorted(all_src)[:10])}")

    if mt5_mappings:
        print(f"\n  MT5 → Dashboard Account Mappings ({len(mt5_mappings)}):")
        seen = set()
        for mt5, dash, ts in mt5_mappings:
            key = f"{mt5}->{dash}"
            if key not in seen:
                print(f"    MT5 {mt5} → Dashboard {dash} ({ts})")
                seen.add(key)

    # ── PHASE 4: Compare with current database ──
    print(f"\n{'='*80}")
    print("PHASE 4: COMPARE WITH CURRENT DATABASE")
    print(f"{'='*80}\n")

    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute('SELECT client_id, last_updated FROM clients_data ORDER BY client_id').fetchall()
        conn.close()
        db_clients = {r[0]: r[1] for r in rows}

        needs_update = 0
        already_fresh = 0
        not_in_db = 0

        for client_id in sorted(merged.keys()):
            push_ts = merged[client_id]['timestamp']
            if client_id not in db_clients:
                print(f"  🆕 {client_id}: Not in DB")
                not_in_db += 1
            elif db_clients[client_id] and db_clients[client_id] > push_ts:
                already_fresh += 1
            else:
                db_ts = db_clients[client_id] or 'None'
                print(f"  📝 {client_id}: Needs update (DB: {db_ts} → Log: {push_ts})")
                needs_update += 1

        if already_fresh:
            print(f"\n  ({already_fresh} clients already have fresher data in DB)")
        print(f"\n  SUMMARY:")
        print(f"    Need update from logs: {needs_update}")
        print(f"    Already fresher in DB: {already_fresh}")
        print(f"    Not in database: {not_in_db}")

    # ── PHASE 4B: NON-PUSH CLIENTS (Dashboard-Only Activity) ──
    print(f"\n{'='*80}")
    print("PHASE 4B: NON-PUSH CLIENTS — NO TRADER APP PUSHES DURING MISSING WEEK")
    print(f"{'='*80}\n")

    non_push = report_non_push_clients(all_pushes)
    if non_push:
        print(f"  {len(non_push)} clients had NO push events in logs (dashboard-only edits lost):\n")
        for c in non_push:
            marker = "⚠️" if c['last_updated'] and '2026-03-2' in c['last_updated'] else "  "
            print(f"  {marker} {c['client_id']:<30} last_updated={c['last_updated'] or 'None':<22} "
                  f"evals={c['eval_count']:<3} funded={c['funded_count']:<2} "
                  f"hedge_accts={c['hedge_accounts']:<3} prop_accts={c['prop_accounts']:<3} "
                  f"vps_accts={c['vps_accounts']}")

        print(f"\n  ⚠️  = last_updated during March 25-29 (may have been active during the week)")
        print(f"\n  NOTE: Dashboard edits (KYC, account additions, stage changes) are NOT stored")
        print(f"  in error logs. They go to the audit_log DB table which was lost with the WAL.")
        print(f"  These clients' current DB state reflects March 25 checkpoint only.")
        print(f"  Manual recovery may be needed for dashboard-only changes made March 26 - April 1.")
    else:
        print(f"  All clients in DB had push events during the week.")

    # ── PHASE 4C: SCAN AUDIT_LOG + DATA_HISTORY ──
    print(f"\n{'='*80}")
    print("PHASE 4C: SCANNING audit_log AND data_history FOR SURVIVING ENTRIES")
    print(f"{'='*80}\n")

    db_scan = scan_audit_log_and_history()
    audit_entries = db_scan.get('audit_entries', [])
    history_entries = db_scan.get('history_entries', [])

    print(f"  audit_log table: {db_scan.get('audit_total', '?')} total rows, "
          f"{len(audit_entries)} in Mar 25 - Apr 2 range")
    print(f"  data_history table: {db_scan.get('history_total', '?')} total rows, "
          f"{len(history_entries)} in Mar 25 - Apr 2 range")

    if audit_entries:
        print(f"\n  SURVIVING AUDIT LOG ENTRIES (Mar 25 - Apr 2):")
        # Group by action type
        actions = defaultdict(int)
        clients_seen = set()
        for entry in audit_entries:
            actions[entry.get('action', '?')] += 1
            detail = entry.get('details', '')
            if detail and 'Client:' in detail:
                cid = detail.split('Client:')[1].split('(')[0].strip()
                clients_seen.add(cid)

        for action, count in sorted(actions.items()):
            print(f"    {action}: {count}")
        if clients_seen:
            print(f"    Unique clients mentioned: {len(clients_seen)}")
            for cid in sorted(clients_seen):
                in_pushes = "✅ also has push data" if cid in all_pushes else "❌ NO push data"
                print(f"      {cid} — {in_pushes}")

        # Show some sample entries
        print(f"\n  Sample entries:")
        for entry in audit_entries[:20]:
            ts = entry.get('timestamp', '?')
            action = entry.get('action', '?')
            detail = entry.get('details', '')[:80]
            user = entry.get('user_identifier', '?')
            print(f"    [{ts}] {action} by {user}: {detail}")
        if len(audit_entries) > 20:
            print(f"    ... and {len(audit_entries) - 20} more")
    else:
        print(f"\n  ❌ No audit_log entries found in the missing week range")
        print(f"     (Expected — these were in the WAL that was truncated)")

    if history_entries:
        print(f"\n  SURVIVING DATA_HISTORY ENTRIES (Mar 25 - Apr 2):")
        for entry in history_entries[:20]:
            cid = entry.get('client_id', '?')
            version = entry.get('version', '?')
            action = entry.get('action', '?')
            source = entry.get('change_source', '?')
            ts = entry.get('created_at', '?')
            in_pushes = "✅" if cid in all_pushes else "❌"
            print(f"    [{ts}] {cid} v{version} ({action} via {source}) {in_pushes}")
        if len(history_entries) > 20:
            print(f"    ... and {len(history_entries) - 20} more")
    else:
        print(f"\n  ❌ No data_history entries found in the missing week range")

    # ── PHASE 4D: API ACTIVITY ANALYSIS ──
    print(f"\n{'='*80}")
    print("PHASE 4D: API ACTIVITY ANALYSIS — DASHBOARD EDIT FREQUENCY")
    print(f"{'='*80}\n")

    update_reqs, login_evts, api_summary = parse_api_activity(all_pushes)

    if update_reqs:
        print(f"  Dashboard update_data requests in logs: {len(update_reqs)}")
        # Group by date
        by_date = defaultdict(int)
        for ts, status, dur in update_reqs:
            date = ts[:10] if ts else 'unknown'
            by_date[date] += 1
        for date in sorted(by_date.keys()):
            print(f"    {date}: {by_date[date]} edits")
        print(f"\n  ⚠️  These requests have NO client ID or payload in the logs.")
        print(f"     {len(update_reqs)} dashboard edits happened but we cannot determine")
        print(f"     which clients were affected or what data was changed.")
    else:
        print(f"  No /api/update_data requests found in logs")

    if api_summary:
        print(f"\n  API Endpoint Summary (top 20):")
        for endpoint, count in sorted(api_summary.items(), key=lambda x: -x[1])[:20]:
            print(f"    {count:>6}x  {endpoint}")

    # ── PHASE 5: DRY RUN ──
    print(f"\n{'='*80}")
    print("PHASE 5: DRY RUN — APPLYING MERGED LOG DATA")
    print(f"{'='*80}")

    updated, skipped, errors = apply_to_database(
        merged, account_maps, session_accounts, dry_run=True
    )

    print(f"\n  DRY RUN RESULTS:")
    print(f"    Would update: {updated}")
    print(f"    Skipped: {skipped}")
    print(f"    Errors: {errors}")

    # ── PHASE 6+7: APPLY + BACKUP + COMPARE (if --apply) ──
    backup_path = None
    if '--apply' in sys.argv:
        print(f"\n{'='*80}")
        print("PHASE 6: APPLYING TO LIVE DATABASE")
        print(f"{'='*80}")

        pre_backup = DB_PATH + f'.pre_reconstruct_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(DB_PATH, pre_backup)
        print(f"\n  Pre-apply backup: {pre_backup}")

        updated, skipped, errors = apply_to_database(
            merged, account_maps, session_accounts, dry_run=False
        )

        print(f"\n  ✅ APPLIED TO LIVE DB:")
        print(f"    Updated: {updated}")
        print(f"    Skipped: {skipped}")
        print(f"    Errors: {errors}")

        # Create clean backup from the PRE-apply state + apply to it
        print(f"\n{'='*80}")
        print("PHASE 7: CREATING RECONSTRUCTED BACKUP DATABASE")
        print(f"{'='*80}")

        backup_path = create_backup_database(merged, account_maps, session_accounts)

        # Compare the PRE-apply backup (original main DB state) vs reconstructed backup
        print(f"\n{'='*80}")
        print("PHASE 8: COMPARING MAIN (PRE-APPLY) vs RECONSTRUCTED BACKUP")
        print(f"{'='*80}")

        compare_databases(pre_backup, backup_path, merged)

    else:
        if updated > 0:
            print(f"\n  To apply these changes + create backup + run comparison:")
            print(f"  python3 _reconstruct_from_logs_v2.py --apply")

    # ── Save full JSON report ──
    report_path = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')
    report = {
        'metadata': {
            'generated': datetime.now().isoformat(),
            'version': 'v2',
            'total_clients': len(all_pushes),
            'total_push_events': total_events,
            'total_all_hedge_writes': total_all_hedge,
            'total_all_farm_writes': total_all_farm,
            'total_merged_hedge_writes': total_merged_hedge,
            'total_merged_farm_writes': total_merged_farm,
            'total_eval_mappings': total_eval_mappings,
            'total_mt5_mappings': len(mt5_mappings),
            'total_farming_accounts': total_farm_accts,
            'total_session_accounts': total_session_accts,
            'total_firms': total_firms,
            'total_source_ids': total_source_ids,
            'non_push_clients': len(non_push),
            'dashboard_edit_requests': len(update_reqs),
            'audit_log_surviving': len(audit_entries),
            'data_history_surviving': len(history_entries),
        },
        'non_push_clients': non_push,
        'audit_log_entries': audit_entries[:100],  # Limit for JSON size
        'data_history_entries': history_entries[:100],
        'api_summary': dict(api_summary),
        'mt5_mappings': [{'mt5': m, 'dashboard': d, 'timestamp': t} for m, d, t in mt5_mappings],
        'clients': {}
    }

    for client_id, pushes in all_pushes.items():
        m = merged.get(client_id, {})
        client_report = {
            'push_count': len(pushes),
            'latest_timestamp': m.get('timestamp', ''),
            'session_accounts': sorted(session_accounts.get(client_id, set())),
            'farming_accounts': {k: v for k, v in farming_accounts.get(client_id, {}).items()},
            'eval_account_map': {str(k): v for k, v in account_maps.get(client_id, {}).items()},
            'firms': firm_map.get(client_id, {}),
            'source_ids': {k: sorted(v) for k, v in source_id_map.get(client_id, {}).items()},
            'merged_hedge_writes': len(m.get('hedge_writes', [])),
            'merged_farm_writes': len(m.get('farming_writes', [])),
            'pushes': [{
                'timestamp': p['timestamp'],
                'deal_count': p['deal_count'],
                'balance': p['balance'],
                'eval_count': p['eval_count'],
                'hedge_writes': len(p['hedge_writes']),
                'farming_writes': len(p['farming_writes']),
                'sessions': len(p.get('sessions', [])),
                'eval_matches': len(p.get('eval_matches', [])),
                'received_groups': p.get('received_groups', 0),
                'received_deals': p.get('received_deals', 0),
                'mt5_balance': p['mt5_balance'],
                'mt5_deposits': p['mt5_deposits'],
                'mt5_withdrawals': p['mt5_withdrawals'],
                'hr_deposits': p['hr_deposits'],
                'hr_withdrawals': p['hr_withdrawals'],
                'hr_balance': p['hr_balance'],
            } for p in pushes]
        }
        report['clients'][client_id] = client_report

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full report saved: {report_path}")

    print(f"\n{'='*100}")
    print("RECONSTRUCTION COMPLETE")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
