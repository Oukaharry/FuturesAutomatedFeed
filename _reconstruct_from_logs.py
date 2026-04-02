#!/usr/bin/env python3
"""
RECONSTRUCT CLIENT DATA FROM SERVER LOGS (Mar 25 - Apr 2)

The logs contain the complete push flow for each client:
  - 📥 Push for {client}: deals, balance, evaluations count
  - ✅ Matched session -> Column: [Hedge Result X] | Row: N | New Value: $X
  - ✅ 🌾 Row N | Hedge Day N: $X (farming)
  - Stats calculated: balance, deposits, withdrawals, actual_hedging
  - FINAL DATA TO SAVE: hedging_review values
  - mt5_account values: balance, total_deposits, total_withdrawals

Strategy:
  Phase 1: Parse ALL error logs → extract per-client push events with cell writes
  Phase 2: For each client, get the LATEST push state
  Phase 3: Apply to database: update evaluations array + statistics + account values

Run: python3 _reconstruct_from_logs.py
"""
import os, sys, gzip, re, json, sqlite3
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')

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
    
    Returns dict: {client_id: [push_event, push_event, ...]}
    Each push_event has:
      - timestamp: str
      - deal_count: int
      - balance: float
      - eval_count: int
      - hedge_writes: [(row, column, value), ...]
      - farming_writes: [(row, day_num, value, date_str), ...]
      - mt5_balance: float
      - mt5_deposits: float
      - mt5_withdrawals: float
      - stats_balance: float
      - stats_deposits: float
      - stats_withdrawals: float
      - stats_hedging: float
      - hr_deposits: float
      - hr_withdrawals: float
      - hr_balance: float
    """
    all_pushes = defaultdict(list)
    
    # Patterns
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
    RE_ACCT_DEP = re.compile(r'account\.total_deposits: \$([\d.,+-]+)')
    RE_AGG = re.compile(r'aggregated_by_comment: (\d+) groups')
    RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    RE_PRESERVE_EVAL = re.compile(r'Preserving (\d+) EXISTING evaluations')
    RE_RECEIVED = re.compile(r'📋 Received (\d+) aggregated groups, (\d+) raw deals')
    RE_SAMPLE_TYPES = re.compile(r"Sample deal types: \[(.+?)\]")
    
    # We also want to capture update_data edits that log action details
    RE_NOTE_POST = re.compile(r'\[REQUEST\] POST /api/notes -> 200')
    
    for log_path, date_range in ERROR_LOGS:
        if not os.path.exists(log_path):
            print(f"  SKIP: {log_path} (not found)")
            continue
        
        size_mb = os.path.getsize(log_path) / 1024 / 1024
        print(f"  Parsing {os.path.basename(log_path)} ({date_range}, {size_mb:.1f}MB)...")
        
        # State machine for tracking the current push context
        # Since pushes can interleave from multiple workers, we use a strategy:
        # - Collect hedge/farming writes into a pending buffer
        # - When we see "📥 Push for {client_id}", flush the buffer to that client
        # - Then collect FINAL DATA / stats lines and associate with the same client
        
        pending_hedge_writes = []
        pending_farming_writes = []
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
                
                # ── Push summary — flush pending writes to this client ──
                m = RE_PUSH.search(line)
                if m:
                    client_id = m.group(1)
                    push_count += 1
                    
                    # Create new push event
                    current_push_client = client_id
                    current_push = {
                        'timestamp': last_timestamp or '',
                        'deal_count': int(m.group(2)),
                        'balance': float(m.group(3)),
                        'eval_count': int(m.group(4)),
                        'hedge_writes': list(pending_hedge_writes),
                        'farming_writes': list(pending_farming_writes),
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
                    
                    # Clear pending buffers
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
                    # Find the push for this client (should be the current or most recent)
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
    
    return all_pushes


def get_latest_pushes(all_pushes):
    """For each client, get the LATEST push event (most recent data)."""
    latest = {}
    for client_id, pushes in all_pushes.items():
        # Sort by timestamp, take last
        sorted_pushes = sorted(pushes, key=lambda p: p['timestamp'])
        latest[client_id] = sorted_pushes[-1]
    return latest


def apply_to_database(latest_pushes, dry_run=True):
    """
    Apply the reconstructed data to the database.
    
    For each client:
    1. Load current evaluations from DB
    2. Apply hedge result writes (Row N, Column X = Value)
    3. Apply farming writes (Row N, Hedge Day N = Value)
    4. Update account dict with MT5 values
    5. Update statistics.hedging_review with logged values
    6. Save back to DB
    """
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    updated = 0
    skipped = 0
    errors = 0
    
    for client_id, push in sorted(latest_pushes.items(), key=lambda x: x[0]):
        try:
            row = conn.execute(
                'SELECT client_id, evaluations, account, statistics, last_updated FROM clients_data WHERE client_id = ?',
                (client_id,)
            ).fetchone()
            
            if not row:
                print(f"  ⚠️  {client_id}: NOT in database (new client?) — skipping")
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
            
            # Print summary
            n_hedge = len(push['hedge_writes'])
            n_farm = len(push['farming_writes'])
            print(f"\n  {'[DRY RUN] ' if dry_run else ''}✅ {client_id} ({push_ts}):")
            print(f"     {n_hedge} hedge writes, {n_farm} farming writes")
            print(f"     balance={push['balance']}, evals={push['eval_count']}, deals={push['deal_count']}")
            if changes:
                for c in changes[:10]:
                    print(f"       → {c}")
                if len(changes) > 10:
                    print(f"       ... and {len(changes) - 10} more changes")
            
            if not dry_run:
                now = datetime.utcnow().isoformat()
                conn.execute('''
                    UPDATE clients_data 
                    SET evaluations = ?, account = ?, statistics = ?, last_updated = ?
                    WHERE client_id = ?
                ''', (
                    json.dumps(evaluations),
                    json.dumps(account),
                    json.dumps(statistics),
                    push_ts,  # Use the log timestamp, not now
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
    
    all_pushes = parse_all_logs()
    
    total_events = sum(len(v) for v in all_pushes.values())
    print(f"\n  TOTAL: {len(all_pushes)} unique clients, {total_events} push events")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Get latest push per client
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 2: LATEST PUSH PER CLIENT")
    print(f"{'='*80}\n")
    
    latest = get_latest_pushes(all_pushes)
    
    # Show all clients with push history
    for client_id in sorted(latest.keys()):
        push = latest[client_id]
        n_pushes = len(all_pushes[client_id])
        n_hedge = len(push['hedge_writes'])
        n_farm = len(push['farming_writes'])
        print(f"  {client_id:<30} {n_pushes:>3} pushes | Latest: {push['timestamp']} | "
              f"deals={push['deal_count']}, bal={push['balance']}, evals={push['eval_count']} | "
              f"hedge_writes={n_hedge}, farm_writes={n_farm}")
    
    # Stats summary
    total_hedge = sum(len(p['hedge_writes']) for p in latest.values())
    total_farm = sum(len(p['farming_writes']) for p in latest.values())
    print(f"\n  SUMMARY:")
    print(f"    Clients with pushes: {len(latest)}")
    print(f"    Total hedge result writes (latest push): {total_hedge}")
    print(f"    Total farming writes (latest push): {total_farm}")
    
    # Show date range coverage
    all_timestamps = [p['timestamp'] for p in latest.values() if p['timestamp']]
    if all_timestamps:
        print(f"    Date range: {min(all_timestamps)} → {max(all_timestamps)}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: Compare with current database
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 3: COMPARE WITH CURRENT DATABASE")
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
                print(f"  🆕 {client_id}: Not in DB (needs to be created)")
                not_in_db += 1
            elif db_clients[client_id] and db_clients[client_id] > push_ts:
                print(f"  ✅ {client_id}: DB already fresher ({db_clients[client_id]} > {push_ts})")
                already_fresh += 1
            else:
                db_ts = db_clients[client_id] or 'None'
                print(f"  📝 {client_id}: Needs update (DB: {db_ts} → Log: {push_ts})")
                needs_update += 1
        
        print(f"\n  SUMMARY:")
        print(f"    Need update from logs: {needs_update}")
        print(f"    Already fresher in DB: {already_fresh}")
        print(f"    Not in database: {not_in_db}")
    else:
        print(f"  Database not found at {DB_PATH}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: DRY RUN — show what would be applied
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 4: DRY RUN — APPLYING LOG DATA TO DATABASE")
    print(f"{'='*80}")
    
    updated, skipped, errors = apply_to_database(latest, dry_run=True)
    
    print(f"\n  DRY RUN RESULTS:")
    print(f"    Would update: {updated}")
    print(f"    Skipped (DB fresher or missing): {skipped}")
    print(f"    Errors: {errors}")
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 5: APPLY (if user confirms)
    # ═══════════════════════════════════════════════════════════════
    if updated > 0:
        print(f"\n{'='*80}")
        print("PHASE 5: READY TO APPLY")
        print(f"{'='*80}")
        print(f"\n  To apply these changes, run:")
        print(f"  python3 _reconstruct_from_logs.py --apply")
    
    if len(sys.argv) > 1 and sys.argv[1] == '--apply':
        print(f"\n{'='*80}")
        print("PHASE 5: APPLYING CHANGES TO DATABASE")
        print(f"{'='*80}")
        
        # Backup first
        backup_path = DB_PATH + f'.backup_reconstruct_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        print(f"\n  Backup created: {backup_path}")
        
        updated, skipped, errors = apply_to_database(latest, dry_run=False)
        
        print(f"\n  ✅ APPLIED:")
        print(f"    Updated: {updated}")
        print(f"    Skipped: {skipped}")
        print(f"    Errors: {errors}")
    
    # ═══════════════════════════════════════════════════════════════
    # Save extracted data for reference
    # ═══════════════════════════════════════════════════════════════
    report_path = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')
    
    # Convert to JSON-serializable
    report = {}
    for client_id, pushes in all_pushes.items():
        report[client_id] = []
        for p in pushes:
            report[client_id].append({
                'timestamp': p['timestamp'],
                'deal_count': p['deal_count'],
                'balance': p['balance'],
                'eval_count': p['eval_count'],
                'hedge_writes_count': len(p['hedge_writes']),
                'farming_writes_count': len(p['farming_writes']),
                'hedge_writes': [(r, c, v) for r, c, v in p['hedge_writes']],
                'farming_writes': [(r, d, v, dt) for r, d, v, dt in p['farming_writes']],
                'mt5_balance': p['mt5_balance'],
                'mt5_deposits': p['mt5_deposits'],
                'mt5_withdrawals': p['mt5_withdrawals'],
                'stats_balance': p['stats_balance'],
                'stats_deposits': p['stats_deposits'],
                'stats_withdrawals': p['stats_withdrawals'],
                'stats_hedging': p['stats_hedging'],
                'hr_deposits': p['hr_deposits'],
                'hr_withdrawals': p['hr_withdrawals'],
                'hr_balance': p['hr_balance'],
            })
    
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full push report saved to: {report_path}")
    
    print(f"\n{'='*100}")
    print("RECONSTRUCTION ANALYSIS COMPLETE")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
