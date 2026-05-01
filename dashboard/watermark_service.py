from dashboard.database import get_connection
from datetime import datetime, timedelta
import logging

def save_daily_profit(client_id, net_profit, date_str=None, source='auto'):
    """
    Saves or updates the daily net profit for a client.
    date_str: 'YYYY-MM-DD', defaults to today.
    """
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Skip write if value hasn't changed for this date
            cursor.execute(
                'SELECT net_profit_complete FROM daily_watermarks WHERE client_id = ? AND date = ?',
                (client_id, date_str)
            )
            existing = cursor.fetchone()
            if existing and abs(float(existing['net_profit_complete']) - float(net_profit)) < 0.005:
                return True  # Unchanged — skip write
            cursor.execute('''
                INSERT INTO daily_watermarks (client_id, date, net_profit_complete, source, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (client_id, date) DO UPDATE
                    SET net_profit_complete = EXCLUDED.net_profit_complete,
                        source = EXCLUDED.source,
                        created_at = CURRENT_TIMESTAMP
            ''', (client_id, date_str, float(net_profit), source))
            conn.commit()
            logging.info(f"Saved daily watermark for {client_id} on {date_str}: ${net_profit} ({source})")
            return True
    except Exception as e:
        logging.error(f"Error saving daily profit: {e}")
        return False

def get_watermark_history(client_id, days=30):
    """
    Returns list of dicts: [{'date': 'YYYY-MM-DD', 'profit': 123.45}, ...]
    Sorted by date.
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date, net_profit_complete 
                FROM daily_watermarks 
                WHERE client_id = ? AND date >= ? 
                ORDER BY date ASC
            ''', (client_id, cutoff_date))
            rows = cursor.fetchall()
            return [{'date': row['date'], 'profit': row['net_profit_complete']} for row in rows]
    except Exception as e:
        logging.error(f"Error getting watermark history: {e}")
        return []

def get_lower_watermark(client_id, days=14):
    """
    Returns the minimum profit recorded in the last X days.
    Returns: {'date': 'YYYY-MM-DD', 'profit': 123.45} or None
    """
    history = get_watermark_history(client_id, days)
    if not history:
        return None
    
    # Calculate min
    min_record = min(history, key=lambda x: x['profit'])
    return min_record

def get_high_watermark(client_id, days=14):
    """
    Returns the maximum profit recorded in the last X days.
    Returns: {'date': 'YYYY-MM-DD', 'profit': 123.45} or None
    """
    history = get_watermark_history(client_id, days)
    if not history:
        return None
    
    # Calculate max
    max_record = max(history, key=lambda x: x['profit'])
    return max_record

def get_bulk_watermarks(days=14):
    """
    Returns a dictionary of watermarks for all clients over the last X days.
    Returns: {client_id: {'high': float, 'low': float}}
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT client_id, MAX(net_profit_complete) as high, MIN(net_profit_complete) as low
                FROM daily_watermarks
                WHERE date >= ?
                GROUP BY client_id
            ''', (cutoff_date,))
            rows = cursor.fetchall()
            # rows are usually tuples or dict-like depending on row_factory.
            # Assuming sqlite3.Row or tuple.
            result = {}
            for row in rows:
                # row accessible by index if tuple, or key if Row.
                # standard sqlite3 without row_factory returns tuples.
                # But dashboard/database.py might set row_factory.
                # Let's assume keys work if Row, or index if tuple?
                # Safer: check type or try/except.
                # Actually, check get_connection implementation.
                try: # dict-like
                    c_id = row['client_id']
                    high = row['high']
                    low = row['low']
                except: # tuple
                    c_id = row[0]
                    high = row[1]
                    low = row[2]
                
                result[c_id] = {'high': high, 'low': low}
            return result
    except Exception as e:
        logging.error(f"Error getting bulk watermarks: {e}")
        return {}

def get_aggregate_watermarks(days=14):
    """
    Returns the SUM of High and Low Watermarks for all clients (where individual values > 0)
    over the last X days.
    Returns: {'hwm': float, 'lwm': float}
    """
    try:
        # Re-using get_bulk_watermarks to get individual HWM/LWM per client
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        bulk_data = get_bulk_watermarks(days)
        
        sum_hwm = 0.0
        sum_lwm = 0.0
        
        for client_id, metrics in bulk_data.items():
            h = metrics.get('high')
            l = metrics.get('low')
            
            # Convert to float and filter > 0
            try:
                h_val = float(h) if h is not None else 0.0
            except: h_val = 0.0
            
            try:
                l_val = float(l) if l is not None else 0.0
            except: l_val = 0.0
            
            if h_val > 0:
                sum_hwm += h_val
                
            if l_val > 0:
                sum_lwm += l_val
                
        return {
            'hwm': sum_hwm,
            'lwm': sum_lwm
        }
    except Exception as e:
        logging.error(f"Error getting aggregate watermarks: {e}")
        return {'hwm': 0.0, 'lwm': 0.0}

def bulk_save_history(client_id, history_data):
    """
    Bulk saves history from external source (e.g., sheet).
    Overwrites all existing daily_watermarks for this client on each import.
    history_data: list of {'date': 'YYYY-MM-DD', 'profit': 123.45}
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Clear existing daily watermarks for this client then insert fresh
            cursor.execute('DELETE FROM daily_watermarks WHERE client_id = ?', (client_id,))
            for record in history_data:
                cursor.execute('''
                    INSERT INTO daily_watermarks (client_id, date, net_profit_complete, source, created_at)
                    VALUES (?, ?, ?, 'sheet_import', CURRENT_TIMESTAMP)
                ''', (client_id, record['date'], float(record['profit'])))
            conn.commit()
            logging.info(f"Overwrote daily_watermarks for {client_id}: {len(history_data)} records")
            return True
    except Exception as e:
        logging.error(f"Error bulk saving history: {e}")
        return False


def save_waterlog_periods(client_id, periods, period_values=None):
    """
    Stores the bi-weekly period schedule for a client.
    periods: list of (from_date_str, to_date_str) in 'YYYY-MM-DD' format.
    period_values: optional dict keyed by from_date_str ->
                   {'low': float, 'high': float, 'split_pct': int}
                   If provided, stores the sheet's actual Low/High/split_pct per period so
                   compute_waterlog_from_db() uses them directly instead of recomputing.
    Existing periods for this client are replaced.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Clear existing schedule for this client then insert fresh
            cursor.execute('DELETE FROM waterlog_periods WHERE client_id = ?', (client_id,))
            for (from_d, to_d) in periods:
                vals = (period_values or {}).get(from_d, {})
                cursor.execute(
                    '''INSERT INTO waterlog_periods
                       (client_id, from_date, to_date, period_low, period_high, split_pct)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (client_id, from_date) DO UPDATE
                           SET to_date = EXCLUDED.to_date,
                               period_low = EXCLUDED.period_low,
                               period_high = EXCLUDED.period_high,
                               split_pct = EXCLUDED.split_pct''',
                    (client_id, from_d, to_d,
                     vals.get('low'),
                     vals.get('high'),
                     vals.get('split_pct'))
                )
            conn.commit()
            logging.info(f"Saved {len(periods)} waterlog periods for {client_id}")
            return True
    except Exception as e:
        logging.error(f"Error saving waterlog periods: {e}")
        return False


def get_waterlog_periods(client_id):
    """
    Returns the stored bi-weekly period schedule for a client.
    Returns: list of (from_date_str, to_date_str) sorted ascending.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT from_date, to_date FROM waterlog_periods WHERE client_id = ? ORDER BY from_date ASC',
                (client_id,)
            )
            return [(row['from_date'], row['to_date']) for row in cursor.fetchall()]
    except Exception as e:
        logging.error(f"Error getting waterlog periods: {e}")
        return []


def get_waterlog_periods_with_values(client_id):
    """
    Returns the stored bi-weekly periods including sheet-imported Low/High/split_pct.
    Returns: list of dicts with from_date, to_date, period_low, period_high, split_pct
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT from_date, to_date, period_low, period_high, split_pct
                   FROM waterlog_periods WHERE client_id = ? ORDER BY from_date ASC''',
                (client_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logging.error(f"Error getting waterlog periods with values: {e}")
        return []


def get_all_daily_watermarks(client_id):
    """
    Returns ALL daily watermark rows for a client (no date cutoff).
    Returns: list of (date_obj, float)
    """
    from datetime import datetime as _dt
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT date, net_profit_complete FROM daily_watermarks WHERE client_id = ? ORDER BY date ASC',
                (client_id,)
            )
            result = []
            for row in cursor.fetchall():
                try:
                    d = _dt.strptime(row['date'], '%Y-%m-%d').date()
                    result.append((d, float(row['net_profit_complete'])))
                except Exception:
                    pass
            return result
    except Exception as e:
        logging.error(f"Error getting all daily watermarks: {e}")
        return []


def get_client_split_pct(client_id):
    """Get the client's default profit split percentage.
    Policy: always 50% unless a per-period override exists in split_pct_overrides.
    Legacy values that may sit in identity.split_pct or waterlog_periods.split_pct
    (imported from sheets) are intentionally ignored — only explicit admin edits
    via /api/client/split_pct_override may deviate from the default.
    Returns int (50)."""
    return 50


def compute_waterlog_from_db(client_id):
    """
    Computes the Profit Share History table entirely from DB data.

    For each period:
      - If period_low/period_high were stored at import time (from the sheet),
        those exact values are used — this keeps historical data identical to
        the Google Sheet.
      - For periods without stored values (new periods after import), Low/High
        are computed from daily_watermarks as min/max.

    Returns dict with 'periods' list and 'last_split_net_profit' float,
    or None if no periods are stored yet (triggers fall-back to sheet).

    Periods before 2/24/2026 use old HWM logic.
    Periods overlapping 2/24-3/20/2026 are condensed into one transition row.
    Periods after 3/20/2026 are generated monthly with new split logic:
      split = 50% of (current_net_profit - last_split_net_profit) if positive.
    """
    from datetime import datetime as _dt, date as _date

    periods_with_vals = get_waterlog_periods_with_values(client_id)
    if not periods_with_vals:
        return None  # No schedule stored — caller falls back to sheet

    daily = get_all_daily_watermarks(client_id)  # [(date_obj, float)]

    TRANSITION_START = _date(2026, 2, 24)
    TRANSITION_END   = _date(2026, 3, 20)

    def _fmt_date(d):
        return f"{d.month}/{d.day}/{d.year}"

    def _fmt_currency(v):
        if v < 0:
            return f"-${abs(v):,.2f}"
        return f"${v:,.2f}"

    # CRITICAL: periods must be sorted oldest-first for correct HWM calculation
    periods_with_vals.sort(key=lambda p: p['from_date'])

    # Load net profit overrides upfront so they feed into HWM / profit split calculation
    np_overrides = get_net_profit_overrides(client_id)

    # Load per-period split percentage overrides
    spct_overrides = get_split_pct_overrides(client_id)

    result = []
    hwm_low = 0.0
    last_pre_transition_net = 0.0  # net profit of the period immediately before transition

    for p in periods_with_vals:
        try:
            from_d = _dt.strptime(p['from_date'], '%Y-%m-%d').date()
            to_d   = _dt.strptime(p['to_date'],   '%Y-%m-%d').date()
        except Exception:
            continue

        # Skip periods that start after the transition end (monthly replaces them)
        if from_d > TRANSITION_END:
            continue

        # Skip periods that overlap transition range — they get condensed below
        overlaps_transition = from_d <= TRANSITION_END and to_d >= TRANSITION_START
        if overlaps_transition:
            continue

        # Use sheet-imported values if available; otherwise recompute from daily data
        if p['period_low'] is not None and p['period_high'] is not None:
            period_low  = float(p['period_low'])
        else:
            in_range = [v for (d, v) in daily if from_d <= d <= to_d]
            period_low  = min(in_range) if in_range else 0.0

        # Apply net profit override if admin edited this period
        np_override_applied = False
        np_key = _fmt_date(from_d)
        if np_key in np_overrides:
            period_low = np_overrides[np_key]
            np_override_applied = True

        # Determine split percentage:
        # Default is always 50%. Only an explicit per-period override (admin edit) changes it.
        # Ignore any split_pct that may have been imported into waterlog_periods from the sheet.
        split_pct = 50
        spct_key = _fmt_date(from_d)
        if spct_key in spct_overrides:
            split_pct = spct_overrides[spct_key]

        # Split only on profit above zero; baseline for gains is max(HWM, 0) so recoveries
        # from negative territory do not multiply split on (current - large_negative).
        effective_hwm = max(hwm_low, 0.0)
        if period_low <= 0:
            profit_split = 0.0
        elif period_low > effective_hwm:
            profit_split = (period_low - effective_hwm) * split_pct / 100
        else:
            profit_split = 0.0
        if period_low > hwm_low:
            hwm_low = period_low

        # Track the net profit of the last pre-transition period
        last_pre_transition_net = period_low

        result.append({
            'from_date':    _fmt_date(from_d),
            'to_date':      _fmt_date(to_d),
            'low':          _fmt_currency(period_low),
            'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
            'split_pct':    split_pct,
        })

    # ── Condensed transition row (2/24 → 3/20) ──────────────────────────
    # Net profit = latest daily value on or before 3/20
    # Split uses the client's configured split percentage
    client_split_pct = get_client_split_pct(client_id)
    condensed_daily = [v for (d, v) in daily if TRANSITION_START <= d <= TRANSITION_END]
    transition_net = condensed_daily[-1] if condensed_daily else 0.0

    # Apply net profit override for transition period
    transition_np_key = _fmt_date(TRANSITION_START)
    if transition_np_key in np_overrides:
        transition_net = np_overrides[transition_np_key]

    # Apply per-period split pct override for transition
    transition_split_pct = client_split_pct
    if transition_np_key in spct_overrides:
        transition_split_pct = spct_overrides[transition_np_key]

    # Use high watermark from all pre-transition periods as base
    effective_base = max(hwm_low, 0.0)
    if transition_net > effective_base and transition_net > 0:
        transition_split = (transition_net - effective_base) * transition_split_pct / 100
    else:
        transition_split = 0.0

    result.append({
        'from_date':    _fmt_date(TRANSITION_START),
        'to_date':      _fmt_date(TRANSITION_END),
        'low':          _fmt_currency(transition_net),
        'profit_split': f"${transition_split:,.0f}" if transition_split > 0 else '$0',
        'split_pct':    transition_split_pct,
    })

    # ── Monthly periods from 3/21 onwards (HWM split logic) ─────────────
    # High watermark = highest net profit across all historical periods
    hwm_net = max(hwm_low, transition_net, 0.0)
    prev_period_net = transition_net
    today = _dt.now().date()
    month_start = TRANSITION_END + timedelta(days=1)  # 3/21/2026

    while month_start <= today:
        # Monthly window: 21st → 20th of next month
        if month_start.month == 12:
            month_end = _date(month_start.year + 1, 1, 20)
        else:
            month_end = _date(month_start.year, month_start.month + 1, 20)

        effective_end = min(month_end, today)

        # Net profit = latest daily watermark value up to effective_end
        in_range = [(d, v) for (d, v) in daily if month_start <= d <= effective_end]
        net_profit = in_range[-1][1] if in_range else prev_period_net

        # Apply net profit override for this monthly period
        monthly_np_key = _fmt_date(month_start)
        if monthly_np_key in np_overrides:
            net_profit = np_overrides[monthly_np_key]

        # Apply per-period split pct override
        monthly_split_pct = client_split_pct
        if monthly_np_key in spct_overrides:
            monthly_split_pct = spct_overrides[monthly_np_key]

        # Split uses the period's split percentage
        # Only if net profit exceeds the highest historical net profit
        effective_base = max(hwm_net, 0.0)
        if net_profit > effective_base and net_profit > 0:
            profit_split = (net_profit - effective_base) * monthly_split_pct / 100
        else:
            profit_split = 0.0

        result.append({
            'from_date':    _fmt_date(month_start),
            'to_date':      _fmt_date(month_end),  # Always show full period end
            'low':          _fmt_currency(net_profit),
            'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
            'split_pct':    monthly_split_pct,
        })

        # For completed months, update the reference point and HWM
        if effective_end >= month_end:
            prev_period_net = net_profit
            if net_profit > hwm_net:
                hwm_net = net_profit

        # Advance to next month
        month_start = month_end + timedelta(days=1)
        if month_start > today:
            break

    # Net profit overrides are now applied during HWM calculation above
    # (no post-processing needed)

    # Apply any manual profit_split overrides (legacy — admin edits from the UI)
    overrides = get_profit_split_overrides(client_id)
    if overrides:
        for period in result:
            key = period['from_date']
            if key in overrides:
                val = overrides[key]
                period['profit_split'] = f"${val:,.0f}" if val > 0 else '$0'
                period['profit_split_override'] = True

    return {
        'periods': result,
        'last_split_net_profit': hwm_net,
    }


# ── Profit Split Override ────────────────────────────────────────────

def _ensure_profit_split_overrides_table():
    """Create the profit_split_overrides table if it doesn't exist."""
    try:
        with get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS profit_split_overrides (
                    client_id   TEXT NOT NULL,
                    from_date   TEXT NOT NULL,
                    amount      REAL NOT NULL,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (client_id, from_date)
                )
            ''')
            conn.commit()
    except Exception as e:
        logging.error(f"Error creating profit_split_overrides table: {e}")


def get_profit_split_overrides(client_id):
    """Return dict of from_date -> amount for all overrides for this client."""
    _ensure_profit_split_overrides_table()
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT from_date, amount FROM profit_split_overrides WHERE client_id = ?',
                (client_id,)
            )
            return {row['from_date']: float(row['amount']) for row in cursor.fetchall()}
    except Exception as e:
        logging.error(f"Error loading profit split overrides: {e}")
        return {}


def save_profit_split_override(client_id, from_date, amount):
    """Save or update a profit split override for a specific period."""
    _ensure_profit_split_overrides_table()
    try:
        with get_connection() as conn:
            conn.execute('''
                INSERT INTO profit_split_overrides (client_id, from_date, amount, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (client_id, from_date) DO UPDATE
                    SET amount = EXCLUDED.amount,
                        updated_at = CURRENT_TIMESTAMP
            ''', (client_id, from_date, float(amount)))
            conn.commit()
            logging.info(f"Saved profit split override for {client_id} period {from_date}: ${amount}")
            return True
    except Exception as e:
        logging.error(f"Error saving profit split override: {e}")
        return False


# ── Net Profit Override ──────────────────────────────────────────────

def _ensure_net_profit_overrides_table():
    """Create the net_profit_overrides table if it doesn't exist."""
    try:
        with get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS net_profit_overrides (
                    client_id   TEXT NOT NULL,
                    from_date   TEXT NOT NULL,
                    amount      REAL NOT NULL,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (client_id, from_date)
                )
            ''')
            conn.commit()
    except Exception as e:
        logging.error(f"Error creating net_profit_overrides table: {e}")


def get_net_profit_overrides(client_id):
    """Return dict of from_date -> amount for all net profit overrides for this client."""
    _ensure_net_profit_overrides_table()
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT from_date, amount FROM net_profit_overrides WHERE client_id = ?',
                (client_id,)
            )
            return {row['from_date']: float(row['amount']) for row in cursor.fetchall()}
    except Exception as e:
        logging.error(f"Error loading net profit overrides: {e}")
        return {}


def save_net_profit_override(client_id, from_date, amount):
    """Save or update a net profit override for a specific period."""
    _ensure_net_profit_overrides_table()
    try:
        with get_connection() as conn:
            conn.execute('''
                INSERT INTO net_profit_overrides (client_id, from_date, amount, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (client_id, from_date) DO UPDATE
                    SET amount = EXCLUDED.amount,
                        updated_at = CURRENT_TIMESTAMP
            ''', (client_id, from_date, float(amount)))
            conn.commit()
            logging.info(f"Saved net profit override for {client_id} period {from_date}: ${amount}")
            return True
    except Exception as e:
        logging.error(f"Error saving net profit override: {e}")
        return False


# ── Split Percentage Override (per-period) ───────────────────────────

def _ensure_split_pct_overrides_table():
    """Create the split_pct_overrides table if it doesn't exist."""
    try:
        with get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS split_pct_overrides (
                    client_id   TEXT NOT NULL,
                    from_date   TEXT NOT NULL,
                    pct         REAL NOT NULL,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (client_id, from_date)
                )
            ''')
            conn.commit()
    except Exception as e:
        logging.error(f"Error creating split_pct_overrides table: {e}")


def get_split_pct_overrides(client_id):
    """Return dict of from_date -> pct for all split percentage overrides for this client."""
    _ensure_split_pct_overrides_table()
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT from_date, pct FROM split_pct_overrides WHERE client_id = ?',
                (client_id,)
            )
            return {row['from_date']: float(row['pct']) for row in cursor.fetchall()}
    except Exception as e:
        logging.error(f"Error loading split pct overrides: {e}")
        return {}


def save_split_pct_override(client_id, from_date, pct):
    """Save or update a split percentage override for a specific period."""
    _ensure_split_pct_overrides_table()
    try:
        pct = float(pct)
        if pct < 0 or pct > 100:
            logging.error(f"Invalid split_pct value {pct} — must be 0-100")
            return False
        with get_connection() as conn:
            conn.execute('''
                INSERT INTO split_pct_overrides (client_id, from_date, pct, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (client_id, from_date) DO UPDATE
                    SET pct = EXCLUDED.pct,
                        updated_at = CURRENT_TIMESTAMP
            ''', (client_id, from_date, pct))
            conn.commit()
            logging.info(f"Saved split pct override for {client_id} period {from_date}: {pct}%")
            return True
    except Exception as e:
        logging.error(f"Error saving split pct override: {e}")
        return False
