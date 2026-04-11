#!/usr/bin/env python3
"""
RECONSTRUCT CLIENT DATA FROM SERVER LOGS (Mar 25 - Apr 2)

The logs contain the complete push flow for each client:
  - 📥 Push for {client}: deals, balance, evaluations count
  - ✅ Matched session -> Column: [Hedge Result X] | Row: N | New Value: $X
  - ✅ 🌾 Row N | Hedge Day N: $X (farming)
  - [SESSION] account_guess=XXX best_phase=YY → account numbers per eval row
  - [MATCHED EVAL] eval_idx=N account=XXXXX phase=YY → account-to-eval mapping
  - [FA PRE-COMPUTE] account=XXX farming_days=N dates=[...] → farming account data
  - MATCHED: MT5 Account X -> Dashboard Account Y → account number mappings
  - Stats calculated: balance, deposits, withdrawals, actual_hedging
  - FINAL DATA TO SAVE: hedging_review values
  - mt5_account values: balance, total_deposits, total_withdrawals

Strategy:
  Phase 1: Parse ALL error logs → extract per-client push events with cell writes + account info
  Phase 2: For each client, get the LATEST push state
  Phase 3: Apply to database: update evaluations + statistics + account values
  Phase 4: Reconstruct account numbers from session/eval matching data
  Phase 5: Create a clean backup database with all reconstructed data

Run:   python3 _reconstruct_from_logs.py           (dry run)
Apply: python3 _reconstruct_from_logs.py --apply    (writes to DB + creates backup)
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


def open_log(path):
    """Open a log file (plain or gzipped)."""
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', errors='replace')
    return open(path, 'r', errors='replace')


def parse_all_logs():
    """
    Parse all error logs and extract per-client push events.
    
    Returns:
      all_pushes: {client_id: [push_event, ...]}
      account_maps: {client_id: {eval_idx: {account, phase, num, ...}}}
      mt5_mappings: [(mt5_account, dashboard_account, timestamp)]
      farming_accounts: {client_id: {account: {days, dates}}}
    """
    all_pushes = defaultdict(list)
    # Account data extracted across ALL pushes (cumulative)
    account_maps = defaultdict(lambda: defaultdict(dict))    # client -> eval_idx -> info
    mt5_mappings = []                                         # (mt5_acct, dash_acct, timestamp)
    farming_accounts = defaultdict(lambda: defaultdict(dict)) # client -> account -> {days, dates}
    session_accounts = defaultdict(set)                       # client -> set of account_guess values
    
    # Patterns — push event data
    RE_PUSH = re.compile(r'📥 Push for (.+?): (\d+) deals, balance=([\d.]+), (\d+) evaluations')
    RE_HEDGE = re.compile(r'✅ Matched session \(Start .+?\) -> Column: \[(.+?)\] \| Row: (\d+) \| New Value: \$([\d.,+-]+)')
    RE_FARM = re.compile(r'✅ 🌾 Row (\d+) \| Hedge Day (\d+): \$([\d.,+-]+) \((\d{4}-\d{2}-\d{2})\)')
    RE_MT5_BAL = re.compile(r'mt5_account\.balance: ([\d.,+-]+)')
    RE_MT5_DEP = re.compile(r'mt5_account\.total_deposits: ([\d.,+-]+)')
    RE_MT5_WD = re.compile(r'mt5_account\.total_withdrawals: ([\d.,+-]+)')
    RE_STATS_BAL = re.compile(r'Current balance: \$([\d.,+-]+)')
    RE_STATS_DEP = re.compile(r'Total deposits: \$([\d.,+-]+)')
    RE_STATS_WD = re.compile(r'Total withdrawals: \$([\d.,+-]+)')
    RE_STATS_HEDGE = re.compile(r'Actual hedging: \$([\d.,+-]+)')
    RE_FINAL = re.compile(r'FINAL DATA TO SAVE for (.+?):')
    RE_HR_DEP = re.compile(r'hedging_review\.total_deposits: \$([\d.,+-]+)')
    RE_HR_WD = re.compile(r'hedging_review\.total_withdrawals: \$([\d.,+-]+)')
    RE_HR_BAL = re.compile(r'hedging_review\.current_balance: \$([\d.,+-]+)')
    RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    
    # Patterns — account number extraction
    RE_SESSION = re.compile(
        r'\[SESSION\] account_guess=(\S+) best_phase=(\S+) best_num=(\S+) '
        r'start=(\S+ \S+) end=(\S+ \S+) profit=([\d.+-]+)'
    )
    RE_MATCHED_EVAL = re.compile(
        r'\[MATCHED EVAL\] eval_idx=(\d+) account=(\S+) phase=(\S+) num=(\S+) drift=(\d+)'
    )
    RE_FA_PRE = re.compile(
        r"\[FA PRE-COMPUTE\] account=(\S+) farming_days=(\d+) dates=\[(.+?)\]"
    )
    RE_MT5_MATCH = re.compile(
        r'MATCHED: MT5 Account (\S+) -> Dashboard Account (\S+)'
    )
    RE_FA_WRITE = re.compile(
        r'\[FA WRITE\] Matched acc_num=(\S+) to pre-computed key=(\S+)'
    )
    RE_RECEIVED = re.compile(r'📋 Received (\d+) aggregated groups, (\d+) raw deals')
    RE_SOURCE_ID = re.compile(r'Source ID\(s\): (.+)')
    
    for log_path, date_range in ERROR_LOGS:
        if not os.path.exists(log_path):
            print(f"  SKIP: {log_path} (not found)")
            continue
        
        size_mb = os.path.getsize(log_path) / 1024 / 1024
        print(f"  Parsing {os.path.basename(log_path)} ({date_range}, {size_mb:.1f}MB)...")
        
        pending_hedge_writes = []
        pending_farming_writes = []
        pending_sessions = []        # session data before push summary
        pending_eval_matches = []    # eval matches before push summary
        pending_fa_accounts = {}     # farming account data before push summary
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
                
                # Extract timestamp
                ts_match = RE_TIMESTAMP.match(line)
                if ts_match:
                    last_timestamp = ts_match.group(1)
                
                # ── Hedge result writes ──
                m = RE_HEDGE.search(line)
                if m:
                    col = m.group(1)
                    row = int(m.group(2))
                    val = float(m.group(3).replace(',', ''))
                    pending_hedge_writes.append((row, col, val))
                    continue
                
                # ── Farming writes ──
                m = RE_FARM.search(line)
                if m:
                    row = int(m.group(1))
                    day = int(m.group(2))
                    val = float(m.group(3).replace(',', ''))
                    date_str = m.group(4)
                    pending_farming_writes.append((row, day, val, date_str))
                    continue
                
                # ── Session account data ──
                m = RE_SESSION.search(line)
                if m:
                    pending_sessions.append({
                        'account_guess': m.group(1),
                        'phase': m.group(2),
                        'num': m.group(3),
                        'start': m.group(4),
                        'end': m.group(5),
                        'profit': float(m.group(6)),
                    })
                    continue
                
                # ── Eval match → account-to-row mapping ──
                m = RE_MATCHED_EVAL.search(line)
                if m:
                    pending_eval_matches.append({
                        'eval_idx': int(m.group(1)),
                        'account': m.group(2),
                        'phase': m.group(3),
                        'num': m.group(4),
                        'drift': int(m.group(5)),
                    })
                    continue
                
                # ── Farming pre-compute ──
                m = RE_FA_PRE.search(line)
                if m:
                    acct = m.group(1)
                    days = int(m.group(2))
                    dates_str = m.group(3)
                    # Parse dates list
                    dates = [d.strip().strip("'\"") for d in dates_str.split(',')]
                    pending_fa_accounts[acct] = {'days': days, 'dates': dates}
                    continue
                
                # ── MT5 account mapping ──
                m = RE_MT5_MATCH.search(line)
                if m:
                    mt5_mappings.append((m.group(1), m.group(2), last_timestamp or ''))
                    continue
                
                # ── Source IDs ──
                m = RE_SOURCE_ID.search(line)
                if m:
                    # These are the raw account numbers used in trades
                    pass  # Already captured via session data
                
                # ── Push summary — flush pending writes to this client ──
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
                        'hedge_writes': list(pending_hedge_writes),
                        'farming_writes': list(pending_farming_writes),
                        'sessions': list(pending_sessions),
                        'eval_matches': list(pending_eval_matches),
                        'fa_accounts': dict(pending_fa_accounts),
                        'mt5_balance': None,
                        'mt5_deposits': None,
                        'mt5_withdrawals': None,
                        'stats_balance': None,
                        'stats_deposits': None,
                        'stats_withdrawals': None,
                        'stats_hedging': None,
                        'hr_deposits': None,
                        'hr_withdrawals': None,
                        'hr_balance': None,
                    }
                    all_pushes[client_id].append(current_push)
                    
                    # Store account maps (cumulative across all pushes)
                    for em in pending_eval_matches:
                        account_maps[client_id][em['eval_idx']] = {
                            'account': em['account'],
                            'phase': em['phase'],
                            'num': em['num'],
                        }
                    for s in pending_sessions:
                        session_accounts[client_id].add(s['account_guess'])
                    for acct, info in pending_fa_accounts.items():
                        farming_accounts[client_id][acct] = info
                    
                    # Clear pending buffers
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    continue
                
                # ── Received line signals new push context starting ──
                m = RE_RECEIVED.search(line)
                if m:
                    # New push starting — clear session/eval buffers for next client
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    continue
                
                # ── MT5 account values (appear after push summary) ──
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
                
                # ── Stats calculated block ──
                if current_push:
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
                
                # ── Push completed → reset context ──
                if '[REQUEST] POST /api/client/push -> 200' in line:
                    current_push = None
                    current_push_client = None
            
            f.close()
            print(f"    → {lines_processed:,} lines, {push_count} push events found")
        
        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback; traceback.print_exc()
    
    return all_pushes, account_maps, mt5_mappings, farming_accounts, session_accounts


def get_latest_pushes(all_pushes):
    """For each client, get the LATEST push event (most recent data)."""
    latest = {}
    for client_id, pushes in all_pushes.items():
        sorted_pushes = sorted(pushes, key=lambda p: p['timestamp'])
        latest[client_id] = sorted_pushes[-1]
    return latest


def apply_to_database(latest_pushes, account_maps, farming_accounts, session_accounts,
                      db_path=None, dry_run=True):
    """
    Apply the reconstructed data to the database.
    
    For each client:
    1. Load current evaluations from DB
    2. Apply hedge result writes (Row N, Column X = Value)
    3. Apply farming writes (Row N, Hedge Day N = Value)
    4. Update account dict with MT5 values
    5. Update statistics.hedging_review with logged values
    6. Reconstruct hedge_accounts from session account data
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
    
    for client_id, push in sorted(latest_pushes.items(), key=lambda x: x[0]):
        try:
            row = conn.execute(
                'SELECT client_id, evaluations, account, statistics, last_updated, '
                'hedge_accounts, prop_accounts FROM clients_data WHERE client_id = ?',
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
            
            # Load current data
            evaluations = json.loads(row['evaluations'] or '[]')
            account = json.loads(row['account'] or '{}')
            statistics = json.loads(row['statistics'] or '{}')
            hedge_accounts = json.loads(row['hedge_accounts'] or '[]')
            prop_accounts = json.loads(row['prop_accounts'] or '[]')
            
            changes = []
            
            # ── Apply hedge result writes ──
            for eval_row, column, value in push['hedge_writes']:
                if eval_row < len(evaluations):
                    old_val = evaluations[eval_row].get(column, 'N/A')
                    evaluations[eval_row][column] = f"{value:.2f}"
                    changes.append(f"eval[{eval_row}][{column}] = {value:.2f} (was {old_val})")
                else:
                    changes.append(f"⚠️ eval[{eval_row}][{column}] = {value:.2f} — ROW OUT OF RANGE (have {len(evaluations)})")
            
            # ── Apply farming writes ──
            for eval_row, day_num, value, date_str in push['farming_writes']:
                field = f'Hedge Day {day_num}'
                date_field = f'_Hedge Day {day_num} Date'
                if eval_row < len(evaluations):
                    old_val = evaluations[eval_row].get(field, 'N/A')
                    evaluations[eval_row][field] = f"{value:.2f}"
                    evaluations[eval_row][date_field] = date_str
                    changes.append(f"eval[{eval_row}][{field}] = {value:.2f} on {date_str} (was {old_val})")
                else:
                    changes.append(f"⚠️ eval[{eval_row}][{field}] = {value:.2f} — ROW OUT OF RANGE")
            
            # ── Update account MT5 values ──
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
            
            # ── Update hedging_review in statistics ──
            hr = statistics.get('hedging_review', {})
            if push['hr_deposits'] is not None:
                hr['total_deposits'] = push['hr_deposits']
            if push['hr_withdrawals'] is not None:
                hr['total_withdrawals'] = push['hr_withdrawals']
            if push['hr_balance'] is not None:
                hr['current_balance'] = push['hr_balance']
            if push['stats_hedging'] is not None:
                hr['actual_hedging_results'] = push['stats_hedging']
            statistics['hedging_review'] = hr
            
            # ── Reconstruct account numbers from session/eval match data ──
            acct_changes = 0
            if client_id in account_maps:
                for eval_idx, info in account_maps[client_id].items():
                    if eval_idx < len(evaluations):
                        ev = evaluations[eval_idx]
                        # The account number from [MATCHED EVAL] is the raw number
                        # The full account_guess (e.g. V2-1170) comes from [SESSION]
                        raw_acct = info['account']
                        phase = info['phase']
                        num = info['num']
                        
                        # Find the full account_guess that contains this raw number
                        full_acct = None
                        if client_id in session_accounts:
                            for sa in session_accounts[client_id]:
                                if raw_acct in sa:
                                    full_acct = sa
                                    break
                        
                        if not full_acct:
                            full_acct = raw_acct
                        
                        # Store account number in the evaluation row
                        old_acct = ev.get('Account Number', ev.get('account_number', ''))
                        if not old_acct or old_acct != full_acct:
                            ev['Account Number'] = full_acct
                            acct_changes += 1
            
            if acct_changes:
                changes.append(f"Updated {acct_changes} evaluation account numbers")
            
            # ── Reconstruct hedge_accounts list from all unique accounts seen ──
            if client_id in session_accounts:
                unique_accounts = sorted(session_accounts[client_id])
                # Build hedge_accounts entries — each is typically {account_number, firm, ...}
                existing_acct_nums = set()
                for ha in hedge_accounts:
                    if isinstance(ha, dict):
                        existing_acct_nums.add(ha.get('account_number', ''))
                    elif isinstance(ha, str):
                        existing_acct_nums.add(ha)
                
                new_accts_added = 0
                for acct_guess in unique_accounts:
                    # Extract firm prefix and number
                    # Pattern: PREFIX-NUMBER (e.g., V2-1170, MFFU-57080, FNFT-75062)
                    parts = acct_guess.split('-', 1)
                    if len(parts) == 2:
                        prefix, number = parts
                    else:
                        prefix, number = '', acct_guess
                    
                    if acct_guess not in existing_acct_nums and number not in existing_acct_nums:
                        # Don't re-add if already exists
                        new_accts_added += 1
                
                if new_accts_added:
                    changes.append(f"Found {new_accts_added} new account numbers from logs (existing: {len(hedge_accounts)})")
            
            # Print summary
            n_hedge = len(push['hedge_writes'])
            n_farm = len(push['farming_writes'])
            n_sessions = len(push.get('sessions', []))
            n_eval_matches = len(push.get('eval_matches', []))
            print(f"\n  {'[DRY RUN] ' if dry_run else ''}✅ {client_id} ({push_ts}):")
            print(f"     {n_hedge} hedge writes, {n_farm} farming writes, "
                  f"{n_sessions} sessions, {n_eval_matches} eval matches")
            print(f"     balance={push['balance']}, evals={push['eval_count']}, deals={push['deal_count']}")
            if changes:
                for c in changes[:15]:
                    print(f"       → {c}")
                if len(changes) > 15:
                    print(f"       ... and {len(changes) - 15} more changes")
            
            if not dry_run:
                conn.execute('''
                    UPDATE clients_data 
                    SET evaluations = ?, account = ?, statistics = ?,
                        last_updated = ?
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


def create_backup_database(latest_pushes, account_maps, farming_accounts, session_accounts):
    """
    Create a clean reconstructed backup database:
    1. Copy current DB
    2. Apply all log-reconstructed data
    3. Verify integrity
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'dashboard.db.reconstructed_{timestamp}')
    
    print(f"\n  Creating backup database: {backup_path}")
    
    # Copy current DB as base
    shutil.copy2(DB_PATH, backup_path)
    
    # Apply all reconstructed data to the backup (NOT dry run)
    updated, skipped, errors = apply_to_database(
        latest_pushes, account_maps, farming_accounts, session_accounts,
        db_path=backup_path, dry_run=False
    )
    
    # Verify integrity
    conn = sqlite3.connect(backup_path)
    try:
        result = conn.execute('PRAGMA integrity_check').fetchone()
        integrity = result[0] if result else 'unknown'
    except Exception as e:
        integrity = f'ERROR: {e}'
    
    # Get stats
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


def main():
    print("=" * 100)
    print("RECONSTRUCT CLIENT DATA FROM SERVER LOGS")
    print(f"Time: {datetime.now()}")
    print("=" * 100)
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: Parse all error logs
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 1: PARSING ALL ERROR LOGS")
    print(f"{'='*80}\n")
    
    all_pushes, account_maps, mt5_mappings, farming_accounts, session_accounts = parse_all_logs()
    
    total_events = sum(len(v) for v in all_pushes.values())
    total_eval_mappings = sum(len(v) for v in account_maps.values())
    total_farm_accts = sum(len(v) for v in farming_accounts.values())
    total_session_accts = sum(len(v) for v in session_accounts.values())
    
    print(f"\n  TOTAL EXTRACTED:")
    print(f"    Unique clients: {len(all_pushes)}")
    print(f"    Push events: {total_events}")
    print(f"    Eval-to-account mappings: {total_eval_mappings}")
    print(f"    MT5 account mappings: {len(mt5_mappings)}")
    print(f"    Farming accounts: {total_farm_accts}")
    print(f"    Unique session accounts: {total_session_accts}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Get latest push per client
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 2: LATEST PUSH PER CLIENT")
    print(f"{'='*80}\n")
    
    latest = get_latest_pushes(all_pushes)
    
    for client_id in sorted(latest.keys()):
        push = latest[client_id]
        n_pushes = len(all_pushes[client_id])
        n_hedge = len(push['hedge_writes'])
        n_farm = len(push['farming_writes'])
        n_accts = len(session_accounts.get(client_id, set()))
        print(f"  {client_id:<30} {n_pushes:>3} pushes | Latest: {push['timestamp']} | "
              f"deals={push['deal_count']}, bal={push['balance']}, evals={push['eval_count']} | "
              f"hedge={n_hedge}, farm={n_farm}, accts={n_accts}")
    
    total_hedge = sum(len(p['hedge_writes']) for p in latest.values())
    total_farm = sum(len(p['farming_writes']) for p in latest.values())
    print(f"\n  SUMMARY:")
    print(f"    Clients with pushes: {len(latest)}")
    print(f"    Total hedge result writes: {total_hedge}")
    print(f"    Total farming writes: {total_farm}")
    
    all_timestamps = [p['timestamp'] for p in latest.values() if p['timestamp']]
    if all_timestamps:
        print(f"    Date range: {min(all_timestamps)} → {max(all_timestamps)}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: Account number report
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 3: ACCOUNT NUMBERS RECOVERED FROM LOGS")
    print(f"{'='*80}\n")
    
    for client_id in sorted(session_accounts.keys()):
        accts = sorted(session_accounts[client_id])
        # Separate by type
        hedge_accts = [a for a in accts if any(p in a.upper() for p in ['CH', 'FD', 'DD']) or 
                       not any(p in a.upper() for p in ['FA'])]
        farm_accts = list(farming_accounts.get(client_id, {}).keys())
        
        print(f"  {client_id}:")
        print(f"    Session accounts ({len(accts)}): {', '.join(accts[:20])}")
        if len(accts) > 20:
            print(f"      ... and {len(accts) - 20} more")
        if farm_accts:
            print(f"    Farming accounts ({len(farm_accts)}): {', '.join(farm_accts[:10])}")
    
    if mt5_mappings:
        print(f"\n  MT5 → Dashboard Account Mappings ({len(mt5_mappings)}):")
        seen = set()
        for mt5, dash, ts in mt5_mappings:
            key = f"{mt5}->{dash}"
            if key not in seen:
                print(f"    MT5 {mt5} → Dashboard {dash} ({ts})")
                seen.add(key)
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: Compare with current database
    # ═══════════════════════════════════════════════════════════════
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
        
        for client_id in sorted(latest.keys()):
            push = latest[client_id]
            push_ts = push['timestamp']
            
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
            print(f"\n  ({already_fresh} clients already have fresher data in DB — not shown)")
        
        print(f"\n  SUMMARY:")
        print(f"    Need update from logs: {needs_update}")
        print(f"    Already fresher in DB: {already_fresh}")
        print(f"    Not in database: {not_in_db}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 5: DRY RUN
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 5: DRY RUN — APPLYING LOG DATA")
    print(f"{'='*80}")
    
    updated, skipped, errors = apply_to_database(
        latest, account_maps, farming_accounts, session_accounts, dry_run=True
    )
    
    print(f"\n  DRY RUN RESULTS:")
    print(f"    Would update: {updated}")
    print(f"    Skipped: {skipped}")
    print(f"    Errors: {errors}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 6: APPLY + BACKUP (if --apply flag)
    # ═══════════════════════════════════════════════════════════════
    if '--apply' in sys.argv:
        print(f"\n{'='*80}")
        print("PHASE 6: APPLYING TO LIVE DATABASE")
        print(f"{'='*80}")
        
        # Pre-apply backup
        pre_backup = DB_PATH + f'.pre_reconstruct_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(DB_PATH, pre_backup)
        print(f"\n  Pre-apply backup: {pre_backup}")
        
        updated, skipped, errors = apply_to_database(
            latest, account_maps, farming_accounts, session_accounts, dry_run=False
        )
        
        print(f"\n  ✅ APPLIED TO LIVE DB:")
        print(f"    Updated: {updated}")
        print(f"    Skipped: {skipped}")
        print(f"    Errors: {errors}")
        
        # Create clean backup database
        print(f"\n{'='*80}")
        print("PHASE 7: CREATING RECONSTRUCTED BACKUP DATABASE")
        print(f"{'='*80}")
        
        backup_path = create_backup_database(
            latest, account_maps, farming_accounts, session_accounts
        )
    else:
        if updated > 0:
            print(f"\n  To apply these changes, run:")
            print(f"  python3 _reconstruct_from_logs.py --apply")
    
    # ═══════════════════════════════════════════════════════════════
    # Save reports
    # ═══════════════════════════════════════════════════════════════
    report_path = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')
    
    report = {
        'metadata': {
            'generated': datetime.now().isoformat(),
            'total_clients': len(all_pushes),
            'total_push_events': total_events,
            'total_eval_mappings': total_eval_mappings,
            'total_mt5_mappings': len(mt5_mappings),
            'total_farming_accounts': total_farm_accts,
            'total_session_accounts': total_session_accts,
        },
        'mt5_mappings': [{'mt5': m, 'dashboard': d, 'timestamp': t} for m, d, t in mt5_mappings],
        'clients': {}
    }
    
    for client_id, pushes in all_pushes.items():
        client_report = {
            'push_count': len(pushes),
            'latest_timestamp': latest[client_id]['timestamp'] if client_id in latest else '',
            'session_accounts': sorted(session_accounts.get(client_id, set())),
            'farming_accounts': {k: v for k, v in farming_accounts.get(client_id, {}).items()},
            'eval_account_map': {str(k): v for k, v in account_maps.get(client_id, {}).items()},
            'pushes': []
        }
        for p in pushes:
            client_report['pushes'].append({
                'timestamp': p['timestamp'],
                'deal_count': p['deal_count'],
                'balance': p['balance'],
                'eval_count': p['eval_count'],
                'hedge_writes': len(p['hedge_writes']),
                'farming_writes': len(p['farming_writes']),
                'sessions': len(p.get('sessions', [])),
                'eval_matches': len(p.get('eval_matches', [])),
                'mt5_balance': p['mt5_balance'],
                'mt5_deposits': p['mt5_deposits'],
                'mt5_withdrawals': p['mt5_withdrawals'],
                'hr_deposits': p['hr_deposits'],
                'hr_withdrawals': p['hr_withdrawals'],
                'hr_balance': p['hr_balance'],
            })
        report['clients'][client_id] = client_report
    
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full report saved: {report_path}")
    
    print(f"\n{'='*100}")
    print("RECONSTRUCTION COMPLETE")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
