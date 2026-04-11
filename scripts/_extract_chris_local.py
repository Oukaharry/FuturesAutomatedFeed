#!/usr/bin/env python3
"""
LOCAL extraction of Chris Ream's COMPLETE evaluation data from error logs.

Parses all logs in ./logs/ (Mar 25 – Apr 3), extracts:
  - Every hedge result cell write  (row, column, value)
  - Every farming day cell write   (row, day, value, date)
  - Every account→row mapping      (eval_idx, account, phase)
  - Every session account           (account_guess, phase, num, profit)
  - MT5 financials + hedging review stats
  - Prop firm derivation from account prefixes

Merges across all ~183 pushes keeping the LATEST value per cell,
then outputs:
  1.  _chris_ream_extracted.json   — full intermediate data
  2.  _chris_ream_full.csv         — dashboard-format CSV
"""
import os, re, json, csv, sys
from collections import defaultdict

CLIENT = "Chris Ream"

# Local log files in chronological order (oldest → newest)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
ERROR_LOGS = [
    ('www.tradeopss.com.error.log.9', 'Mar 25-26'),
    ('www.tradeopss.com.error.log.8', 'Mar 26-27'),
    ('www.tradeopss.com.error.log.7', 'Mar 27-28'),
    ('www.tradeopss.com.error.log.6', 'Mar 28-29'),
    ('www.tradeopss.com.error.log.5', 'Mar 29-30'),
    ('www.tradeopss.com.error.log.4', 'Mar 30-31'),
    ('www.tradeopss.com.error.log.2', 'Mar 31-Apr 2'),
    ('www.tradeopss.com.error.log.1', 'Apr 2-3'),
]

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

# Reverse map: firm name → standard prefix (for fixing partial account numbers)
FIRM_TO_PREFIX = {
    'FundedNext': 'FNFT',
    'My Funded Futures': 'MFFU',
    'TradeDay': 'TDF',
    'Tradeify': 'TDFY',
    'Topstep': 'V2',
    'Alpha Futures': 'AFAD',
}

# Pre-existing MT5 long-form prefixes — already correct values, never overwrite
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
    """Check if account value is a pre-existing MT5 long-form string."""
    if not val:
        return False
    upper = str(val).upper()
    return any(upper.startswith(p) for p in PRE_EXISTING_PREFIXES)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: PARSE ALL LOGS
# ═══════════════════════════════════════════════════════════════════════

def parse_all_logs():
    """Parse every local log, extract ALL push events for Chris Ream."""

    all_pushes = []
    account_maps = defaultdict(list)   # eval_idx → [{account, phase, num}, ...]
    session_accounts = set()           # all account_guess values
    farming_accounts = {}              # account → {days, dates}
    firm_map = {}                      # account → firm name

    # Cell-write patterns
    RE_PUSH     = re.compile(r'📥 Push for (.+?): (\d+) deals, balance=([\d.]+), (\d+) evaluations')
    RE_HEDGE    = re.compile(r'✅ Matched session \(Start (.+?)\) -> Column: \[(.+?)\] \| Row: (\d+) \| New Value: \$([\d.,+-]+)')
    RE_FARM     = re.compile(r'✅ 🌾 Row (\d+) \| Hedge Day (\d+): \$([\d.,+-]+) \((\d{4}-\d{2}-\d{2})\)')

    # MT5 account values
    RE_MT5_BAL  = re.compile(r'mt5_account\.balance: ([\d.,+-]+)')
    RE_MT5_DEP  = re.compile(r'mt5_account\.total_deposits: ([\d.,+-]+)')
    RE_MT5_WD   = re.compile(r'mt5_account\.total_withdrawals: ([\d.,+-]+)')

    # Stats calculated
    RE_STATS_BAL   = re.compile(r'Current balance: \$([\d.,+-]+)')
    RE_STATS_DEP   = re.compile(r'Total deposits: \$([\d.,+-]+)')
    RE_STATS_WD    = re.compile(r'Total withdrawals: \$([\d.,+-]+)')
    RE_STATS_HEDGE = re.compile(r'Actual hedging: \$([\d.,+-]+)')

    # FINAL DATA TO SAVE
    RE_FINAL       = re.compile(r'FINAL DATA TO SAVE for (.+?):')
    RE_HR_DEP      = re.compile(r'hedging_review\.total_deposits: \$([\d.,+-]+)')
    RE_HR_WD       = re.compile(r'hedging_review\.total_withdrawals: \$([\d.,+-]+)')
    RE_HR_BAL      = re.compile(r'hedging_review\.current_balance: \$([\d.,+-]+)')

    # Account matching
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
    RE_FA_SKIP = re.compile(
        r'\[FA SKIP\] eval_idx=(\d+) inactive.*P1=\'(\S+)\' Funded=\'(\S*)\''
    )
    RE_RECEIVED  = re.compile(r'📋 Received (\d+) aggregated groups, (\d+) raw deals')
    RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    RE_FIRM = re.compile(r'📂 (.+?) \((\d+) trades?\)')
    RE_DASH_ACCT = re.compile(r'👤 Dashboard Account: (\S+) \((\d+) trades?\)')
    RE_PHASE_ROW = re.compile(r'🏷️\s*Phase (\S+) -> \[(.+?)\] \(Row #(\d+)\)')
    RE_SOURCE_ID = re.compile(r'Source ID\(s\): (.+)')

    total_pushes_all_clients = 0
    chris_pushes = 0

    for log_file, date_range in ERROR_LOGS:
        log_path = os.path.join(LOG_DIR, log_file)
        if not os.path.exists(log_path):
            print(f"  SKIP: {log_file} (not found)")
            continue

        size_mb = os.path.getsize(log_path) / 1024 / 1024
        print(f"  Parsing {log_file} ({date_range}, {size_mb:.1f}MB)...")

        # Pending buffers — collected between pushes
        pending_hedge_writes = []
        pending_farming_writes = []
        pending_sessions = []
        pending_eval_matches = []
        pending_fa_accounts = {}
        pending_fa_skips = []
        pending_source_ids = {}
        pending_phase_rows = []
        pending_firm = None
        pending_dash_acct = None

        current_push_client = None
        current_push = None
        last_timestamp = None
        lines_processed = 0
        push_count = 0

        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                lines_processed += 1
                line = line.strip()

                ts_match = RE_TIMESTAMP.match(line)
                if ts_match:
                    last_timestamp = ts_match.group(1)

                # ── Hedge result writes ──
                m = RE_HEDGE.search(line)
                if m:
                    sess_start, col, row, val = m.group(1), m.group(2), int(m.group(3)), float(m.group(4).replace(',', ''))
                    pending_hedge_writes.append({
                        'row': row, 'col': col, 'val': val,
                        'timestamp': last_timestamp or '', 'sess_start': sess_start
                    })
                    continue

                # ── Farming writes ──
                m = RE_FARM.search(line)
                if m:
                    pending_farming_writes.append({
                        'row': int(m.group(1)), 'day': int(m.group(2)),
                        'val': float(m.group(3).replace(',', '')),
                        'date': m.group(4), 'timestamp': last_timestamp or ''
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
                    # Always capture account names globally (handles interleaved concurrent pushes)
                    session_accounts.add(m.group(1))
                    continue

                # ── Eval match ──
                m = RE_MATCHED_EVAL.search(line)
                if m:
                    pending_eval_matches.append({
                        'eval_idx': int(m.group(1)), 'account': m.group(2),
                        'phase': m.group(3), 'num': m.group(4),
                        'drift': m.group(5),
                    })
                    continue

                # ── FA PRE-COMPUTE ──
                m = RE_FA_PRE.search(line)
                if m:
                    acct = m.group(1)
                    days = int(m.group(2))
                    dates = [d.strip().strip("'\"") for d in m.group(3).split(',')]
                    pending_fa_accounts[acct] = {'days': days, 'dates': dates}
                    continue

                # ── FA SKIP (inactive eval row) ──
                m = RE_FA_SKIP.search(line)
                if m:
                    pending_fa_skips.append({
                        'eval_idx': int(m.group(1)),
                        'status_p1': m.group(2),
                        'status_funded': m.group(3),
                    })
                    continue

                # ── Firm info ──
                m = RE_FIRM.search(line)
                if m:
                    pending_firm = m.group(1)
                    continue

                # ── Dashboard account detail ──
                m = RE_DASH_ACCT.search(line)
                if m:
                    pending_dash_acct = m.group(1)
                    continue

                # ── Phase/Row detail ──
                m = RE_PHASE_ROW.search(line)
                if m:
                    pending_phase_rows.append({
                        'phase': m.group(1), 'field': m.group(2),
                        'row': int(m.group(3)),
                        'account': pending_dash_acct,
                    })
                    continue

                # ── Source IDs ──
                m = RE_SOURCE_ID.search(line)
                if m:
                    ids = [s.strip() for s in m.group(1).split(',')]
                    if pending_dash_acct:
                        if pending_dash_acct not in pending_source_ids:
                            pending_source_ids[pending_dash_acct] = set()
                        pending_source_ids[pending_dash_acct].update(ids)
                    continue

                # ── Received line — NEW push context ──
                m = RE_RECEIVED.search(line)
                if m:
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    pending_fa_skips = []
                    pending_source_ids = {}
                    pending_phase_rows = []
                    pending_firm = None
                    pending_dash_acct = None
                    continue

                # ── Push summary → flush to client ──
                m = RE_PUSH.search(line)
                if m:
                    client_id = m.group(1)
                    total_pushes_all_clients += 1

                    if client_id == CLIENT:
                        push_count += 1
                        chris_pushes += 1
                        push_data = {
                            'timestamp': last_timestamp or '',
                            'deal_count': int(m.group(2)),
                            'balance': float(m.group(3)),
                            'eval_count': int(m.group(4)),
                            'hedge_writes': list(pending_hedge_writes),
                            'farming_writes': list(pending_farming_writes),
                            'sessions': list(pending_sessions),
                            'eval_matches': list(pending_eval_matches),
                            'fa_accounts': dict(pending_fa_accounts),
                            'fa_skips': list(pending_fa_skips),
                            'phase_rows': list(pending_phase_rows),
                            'mt5_balance': None, 'mt5_deposits': None, 'mt5_withdrawals': None,
                            'stats_balance': None, 'stats_deposits': None,
                            'stats_withdrawals': None, 'stats_hedging': None,
                            'hr_deposits': None, 'hr_withdrawals': None, 'hr_balance': None,
                        }
                        all_pushes.append(push_data)
                        current_push = push_data

                        # Accumulate global maps
                        for em in pending_eval_matches:
                            entry = {'account': em['account'], 'phase': em['phase'], 'num': em['num']}
                            existing = account_maps[em['eval_idx']]
                            if entry not in existing:
                                existing.append(entry)

                        # Link hedge writes → sessions by start time
                        if pending_sessions and pending_hedge_writes:
                            sess_by_start = {}
                            for s in pending_sessions:
                                sess_by_start[s['start']] = s
                            for hw in pending_hedge_writes:
                                hw_sess_start = hw.get('sess_start', '')
                                if not hw_sess_start:
                                    continue
                                sess = sess_by_start.get(hw_sess_start)
                                if not sess:
                                    continue
                                acct_guess = sess['account_guess']
                                acct_partial = acct_guess.rsplit('-', 1)[-1] if '-' in acct_guess else acct_guess
                                entry = {'account': acct_partial, 'phase': sess['phase'], 'num': sess['num']}
                                existing = account_maps[hw['row']]
                                if entry not in existing:
                                    existing.append(entry)

                        for s in pending_sessions:
                            session_accounts.add(s['account_guess'])
                        for acct, info in pending_fa_accounts.items():
                            farming_accounts[acct] = info
                    else:
                        current_push = None

                    # Clear pending
                    pending_hedge_writes = []
                    pending_farming_writes = []
                    pending_sessions = []
                    pending_eval_matches = []
                    pending_fa_accounts = {}
                    pending_fa_skips = []
                    pending_source_ids = {}
                    pending_phase_rows = []
                    pending_firm = None
                    pending_dash_acct = None
                    continue

                # ── Post-push values (mt5, stats, FINAL) — only if current push is Chris ──
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

                # ── FINAL DATA TO SAVE ──
                m = RE_FINAL.search(line)
                if m:
                    if m.group(1) == CLIENT and all_pushes:
                        current_push = all_pushes[-1]
                    else:
                        current_push = None
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

                # ── Push completed → reset ──
                if '[REQUEST] POST /api/client/push -> 200' in line:
                    current_push = None

        print(f"    → {lines_processed:,} lines, {push_count} Chris Ream pushes")

    print(f"\n  Total: {chris_pushes} Chris Ream pushes across {total_pushes_all_clients} total pushes")
    print(f"  Session accounts: {len(session_accounts)}")
    print(f"  Account maps: {len(account_maps)} eval rows")
    print(f"  Farming accounts: {len(farming_accounts)}")

    return all_pushes, account_maps, session_accounts, farming_accounts


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: MERGE ALL PUSHES
# ═══════════════════════════════════════════════════════════════════════

def merge_pushes(all_pushes):
    """Merge all pushes keeping latest value per (row, col) cell."""
    sorted_pushes = sorted(all_pushes, key=lambda p: p['timestamp'])

    # Merge hedge writes: (row, col) → (val, timestamp)
    hedge_map = {}
    for push in sorted_pushes:
        for hw in push['hedge_writes']:
            key = (hw['row'], hw['col'])
            ts = hw['timestamp']
            if key not in hedge_map or ts >= hedge_map[key][1]:
                hedge_map[key] = (hw['val'], ts)

    # Merge farming writes: (row, day) → (val, date_str, timestamp)
    farm_map = {}
    for push in sorted_pushes:
        for fw in push['farming_writes']:
            key = (fw['row'], fw['day'])
            ts = fw['timestamp']
            if key not in farm_map or ts >= farm_map[key][2]:
                farm_map[key] = (fw['val'], fw['date'], ts)

    # Latest push for scalar values
    latest = sorted_pushes[-1]

    # Scan backwards for missing scalars
    scalars = {}
    for field in ('mt5_balance', 'mt5_deposits', 'mt5_withdrawals',
                  'hr_deposits', 'hr_withdrawals', 'hr_balance',
                  'stats_balance', 'stats_deposits', 'stats_withdrawals', 'stats_hedging'):
        val = latest.get(field)
        if val is None:
            for p in reversed(sorted_pushes[:-1]):
                if p.get(field) is not None:
                    val = p[field]
                    break
        scalars[field] = val

    return {
        'timestamp': latest['timestamp'],
        'deal_count': latest['deal_count'],
        'balance': latest['balance'],
        'eval_count': latest['eval_count'],
        'total_pushes': len(all_pushes),
        'hedge_map': hedge_map,
        'farm_map': farm_map,
        'scalars': scalars,
    }


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: BUILD EVALUATIONS + CSV
# ═══════════════════════════════════════════════════════════════════════

def build_evaluations(merged, account_maps, session_accounts, farming_accounts):
    """Build the full evaluations array from merged data."""
    eval_count = merged['eval_count']
    print(f"\n  Building {eval_count} evaluation rows...")

    # Initialize empty rows
    evaluations = [{} for _ in range(eval_count)]

    # ── 1. Place hedge result values ──
    hedge_ok = 0
    for (row, col), (val, _ts) in merged['hedge_map'].items():
        if 0 <= row < eval_count:
            evaluations[row][col] = f"{val:.2f}"
            hedge_ok += 1
    print(f"  Hedge result writes applied: {hedge_ok}")

    # ── 2. Place farming day values ──
    farm_ok = 0
    for (row, day), (val, date_str, _ts) in merged['farm_map'].items():
        if 0 <= row < eval_count:
            evaluations[row][f'Hedge Day {day}'] = f"{val:.2f}"
            farm_ok += 1
    print(f"  Farming day writes applied: {farm_ok}")

    # ── 3. Calculate Hedge Net for eval phase ──
    hedge_net_count = 0
    for row_idx, ev in enumerate(evaluations):
        hr_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                   'Hedge Result 4', 'Hedge Result 5']
        vals = []
        for c in hr_cols:
            v = ev.get(c, '')
            if v:
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        if vals:
            ev['Hedge Net'] = f"{sum(vals):.2f}"
            hedge_net_count += 1

    # ── 4. Calculate Hedge Net.1 for funded phase ──
    hedge_net1_count = 0
    for row_idx, ev in enumerate(evaluations):
        hr_cols = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                   'Hedge Result 4.1', 'Hedge Result 5.1',
                   'Hedge Result 6', 'Hedge Result 7']
        vals = []
        for c in hr_cols:
            v = ev.get(c, '')
            if v:
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        if vals:
            ev['Hedge Net.1'] = f"{sum(vals):.2f}"
            hedge_net1_count += 1
    print(f"  Hedge Net calculated: {hedge_net_count} eval, {hedge_net1_count} funded")

    # ── 5. Place account numbers from eval_account_map ──
    # session_accounts includes full account names like MFFU-66028, FNFT-90637
    # Build lookup: partial → full account name
    session_lookup = {}
    for sa in session_accounts:
        session_lookup[sa] = sa
        if '-' in sa:
            partial = sa.rsplit('-', 1)[-1]
            session_lookup[partial] = sa

    def resolve_account(partial_acct):
        """Resolve a partial account number to full (prefix-number) form."""
        # 1. Direct session lookup
        full = session_lookup.get(partial_acct)
        if full and '-' in full:
            return full
        # 2. Search all session accounts for suffix match
        for sa in sorted(session_accounts):
            if '-' in sa and sa.endswith('-' + partial_acct):
                return sa
        # 3. Already has a prefix
        if '-' in partial_acct:
            return partial_acct
        return partial_acct  # return as-is, will fix in post-processing

    acct_placed = 0
    for row_idx, entries in sorted(account_maps.items()):
        if row_idx >= eval_count:
            continue
        for entry in entries:
            acct = entry['account']
            phase = entry['phase'].upper()
            # Resolve to full session account
            full_acct = resolve_account(acct)

            if phase.startswith('CH'):
                field = 'Account #'
            elif phase in ('FA', 'FD', 'DD'):
                field = 'Account #.1'
            else:
                field = 'Account #'

            existing = evaluations[row_idx].get(field, '')
            if not existing or not is_pre_existing(existing):
                evaluations[row_idx][field] = full_acct
                acct_placed += 1
                break  # One account per phase field per row

    print(f"  Account numbers placed: {acct_placed}")

    # ── 6. Derive Prop Firm from account numbers ──
    firm_count = 0
    for ev in evaluations:
        if ev.get('Prop Firm'):
            continue
        acct = ev.get('Account #') or ev.get('Account #.1', '')
        if acct:
            firm = derive_firm(acct)
            if firm:
                ev['Prop Firm'] = firm
                firm_count += 1
    print(f"  Prop Firm derived: {firm_count}")

    # ── 7. Fix remaining partial account numbers using Prop Firm ──
    partial_fixed = 0
    for ev in evaluations:
        for field in ('Account #', 'Account #.1'):
            val = ev.get(field, '').strip()
            if val and '-' not in val and not is_pre_existing(val):
                # Partial — try to prefix from Prop Firm
                firm = ev.get('Prop Firm', '')
                prefix = FIRM_TO_PREFIX.get(firm)
                if prefix:
                    ev[field] = f"{prefix}-{val}"
                    partial_fixed += 1
    print(f"  Partial account numbers fixed via Prop Firm: {partial_fixed}")

    # ── 7. Summary ──
    rows_with_data = sum(1 for ev in evaluations if any(v for v in ev.values()))
    rows_empty = eval_count - rows_with_data
    print(f"\n  Rows with data: {rows_with_data}")
    print(f"  Empty rows: {rows_empty}")

    return evaluations


def write_csv(evaluations, merged, output_path):
    """Write evaluations to CSV in dashboard column order."""
    # Build column list: dashboard order + any extras found
    all_keys = set()
    for ev in evaluations:
        all_keys.update(ev.keys())

    columns = ['Row #']
    for c in DASHBOARD_COLUMN_ORDER:
        if c in all_keys or True:  # Include all standard columns
            columns.append(c)
    # Add any extra columns not in standard order
    extra = sorted(all_keys - set(DASHBOARD_COLUMN_ORDER) - {'Row #'})
    for c in extra:
        if not c.startswith('_'):  # Skip internal fields
            columns.append(c)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for idx, ev in enumerate(evaluations):
            row = dict(ev)
            row['Row #'] = idx
            writer.writerow(row)

        # Write stats summary after a blank row
        writer.writerow({})
        stats_row = {'Row #': '--- Statistics ---'}
        s = merged['scalars']
        if s.get('mt5_balance') is not None:
            stats_row['Prop Firm'] = f"MT5 Balance: ${s['mt5_balance']:,.2f}"
        if s.get('mt5_deposits') is not None:
            stats_row['Account Size'] = f"MT5 Total Deposits: ${s['mt5_deposits']:,.2f}"
        if s.get('mt5_withdrawals') is not None:
            stats_row['Date Purchased'] = f"MT5 Withdrawals: ${s['mt5_withdrawals']:,.2f}"
        if s.get('stats_balance') is not None:
            stats_row['Fee'] = f"Calculated Balance: ${s['stats_balance']:,.2f}"
        if s.get('stats_hedging') is not None:
            stats_row['Date Started'] = f"Actual Hedging: ${s['stats_hedging']:,.2f}"
        if s.get('hr_deposits') is not None:
            stats_row['Date Ended'] = f"HR Deposits: ${s['hr_deposits']:,.2f}"
        if s.get('hr_withdrawals') is not None:
            stats_row['Status P1'] = f"HR Withdrawals: ${s['hr_withdrawals']:,.2f}"
        if s.get('hr_balance') is not None:
            stats_row['Account #'] = f"HR Balance: ${s['hr_balance']:,.2f}"
        writer.writerow(stats_row)

    return len(columns)


def write_json(all_pushes, account_maps, session_accounts, farming_accounts, merged, output_path):
    """Write full extracted data to JSON for reference."""
    data = {
        'client': CLIENT,
        'extraction_date': '2026-04-04',
        'total_pushes': len(all_pushes),
        'latest_timestamp': merged['timestamp'],
        'latest_deal_count': merged['deal_count'],
        'latest_eval_count': merged['eval_count'],
        'latest_balance': merged['balance'],
        'scalars': merged['scalars'],
        'session_accounts': sorted(session_accounts),
        'session_account_count': len(session_accounts),
        'farming_accounts': {k: v for k, v in farming_accounts.items()},
        'account_maps': {
            str(k): v for k, v in sorted(account_maps.items())
        },
        'account_map_row_count': len(account_maps),
        'hedge_writes_merged': len(merged['hedge_map']),
        'farming_writes_merged': len(merged['farm_map']),
        # Raw write maps for server-side apply
        'hedge_writes': [
            {'row': r, 'col': c, 'val': v}
            for (r, c), (v, _ts) in sorted(merged['hedge_map'].items())
        ],
        'farming_writes': [
            {'row': r, 'day': d, 'val': v, 'date': ds}
            for (r, d), (v, ds, _ts) in sorted(merged['farm_map'].items())
        ],
        'push_timeline': [
            {
                'timestamp': p['timestamp'],
                'deals': p['deal_count'],
                'balance': p['balance'],
                'evals': p['eval_count'],
                'hedge_writes': len(p['hedge_writes']),
                'farming_writes': len(p['farming_writes']),
                'sessions': len(p['sessions']),
                'eval_matches': len(p['eval_matches']),
            }
            for p in sorted(all_pushes, key=lambda x: x['timestamp'])
        ],
    }
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4 (OPTIONAL): MERGE WITH DB BACKUP
# ═══════════════════════════════════════════════════════════════════════

def merge_with_db(evaluations, db_path):
    """
    If a DB backup is available locally, merge the log-extracted data
    on top of the existing evaluation data.
    This preserves:
      - Prop Firm, Account Size, Date Purchased, Fee
      - Date Started, Date Ended, Status P1, Status
      - Account # and Account #.1 (pre-existing MT5 values)
      - Payout/Date fields
    And overlays the log-extracted:
      - Hedge Results
      - Farming Days
      - Account numbers from eval_account_map (if row was empty)
    """
    import sqlite3

    if not os.path.exists(db_path):
        print(f"  DB not found: {db_path}")
        return evaluations

    print(f"\n  Loading DB: {db_path}")
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        row = conn.execute(
            "SELECT evaluations, statistics FROM clients_data WHERE client_id=?",
            (CLIENT,)
        ).fetchone()
    except Exception as e:
        print(f"  DB error: {e}")
        conn.close()
        return evaluations
    conn.close()

    if not row:
        print(f"  {CLIENT} not found in DB")
        return evaluations

    db_evals = json.loads(row[0] or '[]')
    db_stats = json.loads(row[1] or '{}')
    print(f"  DB has {len(db_evals)} evaluation rows")
    print(f"  Log extracted {len(evaluations)} rows")

    # Use the larger as the base
    max_rows = max(len(db_evals), len(evaluations))
    merged_evals = []

    for i in range(max_rows):
        db_row = db_evals[i] if i < len(db_evals) else {}
        log_row = evaluations[i] if i < len(evaluations) else {}

        # Start from DB row as base
        merged = dict(db_row)

        # Overlay log-extracted values (hedge results, farming, accounts)
        for key, val in log_row.items():
            if not val:
                continue
            # Always overlay hedge results and farming days from logs (these are the recovered data)
            if 'Hedge Result' in key or 'Hedge Net' in key or 'Hedge Day' in key:
                merged[key] = val
            # Only overlay account numbers if DB doesn't have a value
            elif key in ('Account #', 'Account #.1'):
                existing = merged.get(key, '')
                if not existing:
                    merged[key] = val
            # Only overlay Prop Firm if DB doesn't have one
            elif key == 'Prop Firm':
                if not merged.get(key):
                    merged[key] = val
            # For anything else, keep DB value if present
            elif not merged.get(key):
                merged[key] = val

        merged_evals.append(merged)

    print(f"  Merged result: {len(merged_evals)} rows")
    return merged_evals


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    # Fix Windows encoding for Unicode output
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description='Extract Chris Ream data from local logs')
    parser.add_argument('--db', help='Path to a local DB backup to merge with')
    args = parser.parse_args()

    print("=" * 70)
    print(f"  EXTRACTING DATA FOR: {CLIENT}")
    print(f"  Log directory: {LOG_DIR}")
    print("=" * 70)

    # Phase 1: Parse
    print("\n── PHASE 1: Parsing logs ──")
    all_pushes, account_maps, session_accounts, farming_accounts = parse_all_logs()

    if not all_pushes:
        print("ERROR: No push data found for Chris Ream!")
        sys.exit(1)

    # Phase 2: Merge
    print("\n── PHASE 2: Merging pushes ──")
    merged = merge_pushes(all_pushes)
    print(f"  Merged hedge cells: {len(merged['hedge_map'])}")
    print(f"  Merged farming cells: {len(merged['farm_map'])}")
    print(f"  Latest push: {merged['timestamp']}, {merged['deal_count']} deals, {merged['eval_count']} evals")

    # Phase 3: Build evaluations
    print("\n── PHASE 3: Building evaluations ──")
    evaluations = build_evaluations(merged, account_maps, session_accounts, farming_accounts)

    # Phase 4: Merge with DB if available
    if args.db:
        print("\n── PHASE 4: Merging with DB backup ──")
        evaluations = merge_with_db(evaluations, args.db)
        # Recalculate hedge nets after merge
        for ev in evaluations:
            hr_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                       'Hedge Result 4', 'Hedge Result 5']
            vals = []
            for c in hr_cols:
                v = ev.get(c, '')
                if v:
                    try:
                        vals.append(float(str(v).replace('$', '').replace(',', '')))
                    except ValueError:
                        pass
            if vals:
                ev['Hedge Net'] = f"{sum(vals):.2f}"

            hr_cols1 = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                        'Hedge Result 4.1', 'Hedge Result 5.1',
                        'Hedge Result 6', 'Hedge Result 7']
            vals1 = []
            for c in hr_cols1:
                v = ev.get(c, '')
                if v:
                    try:
                        vals1.append(float(str(v).replace('$', '').replace(',', '')))
                    except ValueError:
                        pass
            if vals1:
                ev['Hedge Net.1'] = f"{sum(vals1):.2f}"

    # Write outputs
    base = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base, '_chris_ream_extracted.json')
    csv_path = os.path.join(base, '_chris_ream_full.csv')

    print("\n── Writing outputs ──")
    write_json(all_pushes, account_maps, session_accounts, farming_accounts, merged, json_path)
    print(f"  JSON: {json_path}")

    col_count = write_csv(evaluations, merged, csv_path)
    print(f"  CSV:  {csv_path} ({col_count} columns)")

    # Summary stats
    print("\n" + "=" * 70)
    print("  EXTRACTION SUMMARY")
    print("=" * 70)
    print(f"  Client:             {CLIENT}")
    print(f"  Total pushes:       {len(all_pushes)}")
    print(f"  Date range:         {all_pushes[0]['timestamp'][:10]} → {all_pushes[-1]['timestamp'][:10]}")
    print(f"  Latest eval count:  {merged['eval_count']}")
    print(f"  Hedge cells merged: {len(merged['hedge_map'])}")
    print(f"  Farming cells:      {len(merged['farm_map'])}")
    print(f"  Session accounts:   {len(session_accounts)}")
    print(f"  Account map rows:   {len(account_maps)}")
    print(f"  Farming accounts:   {len(farming_accounts)}")

    rows_with_hedge = sum(1 for ev in evaluations if any(k.startswith('Hedge Result') for k in ev))
    rows_with_farm = sum(1 for ev in evaluations if any(k.startswith('Hedge Day') for k in ev))
    rows_with_acct = sum(1 for ev in evaluations if ev.get('Account #') or ev.get('Account #.1'))
    rows_with_firm = sum(1 for ev in evaluations if ev.get('Prop Firm'))
    print(f"\n  Rows with hedge results: {rows_with_hedge}")
    print(f"  Rows with farming data:  {rows_with_farm}")
    print(f"  Rows with account #:     {rows_with_acct}")
    print(f"  Rows with prop firm:     {rows_with_firm}")
    print(f"  Empty rows:              {merged['eval_count'] - rows_with_hedge}")

    # List session accounts
    print(f"\n  Session accounts ({len(session_accounts)}):")
    for sa in sorted(session_accounts):
        firm = derive_firm(sa) or '?'
        print(f"    {sa:30s}  → {firm}")

    s = merged['scalars']
    print(f"\n  Financial summary (latest):")
    print(f"    MT5 Balance:      ${s.get('mt5_balance', 0):,.2f}")
    print(f"    MT5 Deposits:     ${s.get('mt5_deposits', 0):,.2f}")
    print(f"    MT5 Withdrawals:  ${s.get('mt5_withdrawals', 0):,.2f}")
    print(f"    Stats Balance:    ${s.get('stats_balance', 0):,.2f}")
    print(f"    Stats Hedging:    ${s.get('stats_hedging', 0):,.2f}")
    print(f"    HR Deposits:      ${s.get('hr_deposits', 0):,.2f}")
    print(f"    HR Withdrawals:   ${s.get('hr_withdrawals', 0):,.2f}")
    print(f"    HR Balance:       ${s.get('hr_balance', 0):,.2f}")


if __name__ == '__main__':
    main()
