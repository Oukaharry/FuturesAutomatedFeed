from collections import defaultdict
from dashboard.database import get_connection
from datetime import datetime, timedelta, date as _date_cls
import calendar
import logging
import threading
import time

# Profit-share schedule after the 3/20/2026 transition:
# twice monthly — periods end on the 15th and the 30th
# (or last day of month when there is no 30th, e.g. February).


def _bimonthly_period_end(period_start):
    """
    Bi-monthly window ending on the 15th or 30th.

    start.day <= 15  → end on the 15th of the same month
    start.day 16–30  → end on the 30th (or last day if month is shorter)
    start.day == 31  → end on the 15th of the next month
    """
    last = calendar.monthrange(period_start.year, period_start.month)[1]
    if period_start.day <= 15:
        return _date_cls(period_start.year, period_start.month, 15)
    end_day = min(30, last)
    if period_start.day <= end_day:
        return _date_cls(period_start.year, period_start.month, end_day)
    if period_start.month == 12:
        return _date_cls(period_start.year + 1, 1, 15)
    return _date_cls(period_start.year, period_start.month + 1, 15)


def _iter_profit_split_periods(month_start, today):
    """Yield (period_start, period_end) on the 15/30 bi-monthly schedule."""
    period_start = month_start
    while period_start <= today:
        period_end = _bimonthly_period_end(period_start)
        yield period_start, period_end
        period_start = period_end + timedelta(days=1)

_WATERLOG_TABLES_ENSURED = False
_WATERLOG_TABLES_LOCK = threading.Lock()
_BULK_CACHE = None
_BULK_CACHE_AT = 0.0
_BULK_CACHE_LOCK = threading.Lock()
_BULK_CACHE_TTL = 90

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

def get_watermark_history(client_id, days=30, start_date=None, end_date=None):
    """
    Returns list of dicts: [{'date': 'YYYY-MM-DD', 'profit': 123.45}, ...]
    Sorted by date.

    If start_date / end_date are provided (YYYY-MM-DD), they take precedence over days.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if start_date or end_date:
                clauses = ['client_id = ?']
                params = [client_id]
                if start_date:
                    clauses.append('date >= ?')
                    params.append(start_date)
                if end_date:
                    clauses.append('date <= ?')
                    params.append(end_date)
                cursor.execute(f'''
                    SELECT date, net_profit_complete
                    FROM daily_watermarks
                    WHERE {' AND '.join(clauses)}
                    ORDER BY date ASC
                ''', params)
            else:
                cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
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


def compute_waterlog_daily_fallback(client_id, _bulk=None):
    """
    Legacy entry point — delegates to monthly computation from daily watermarks.
    Kept for callers that still invoke this name directly.
    """
    if _bulk is not None:
        daily = list(_bulk['daily'].get(client_id, []))
    else:
        daily = get_all_daily_watermarks(client_id)
    if not daily:
        return None
    result = _compute_waterlog_monthly_from_daily(client_id, daily, _bulk=_bulk)
    if result:
        result['_source'] = 'daily_watermarks_fallback'
    return result


def ensure_waterlog_override_tables():
    """Create override tables once per process (not per client)."""
    global _WATERLOG_TABLES_ENSURED
    if _WATERLOG_TABLES_ENSURED:
        return
    with _WATERLOG_TABLES_LOCK:
        if _WATERLOG_TABLES_ENSURED:
            return
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
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS split_pct_overrides (
                        client_id   TEXT NOT NULL,
                        from_date   TEXT NOT NULL,
                        pct         REAL NOT NULL,
                        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (client_id, from_date)
                    )
                ''')
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
            _WATERLOG_TABLES_ENSURED = True
        except Exception as e:
            logging.error(f"Error ensuring waterlog override tables: {e}")


def prefetch_waterlog_bulk(force_refresh=False):
    """
    Load waterlog periods, daily marks, and all overrides in one DB connection.
    Used by super-admin profit split endpoints to avoid N×clients pool exhaustion.
    """
    global _BULK_CACHE, _BULK_CACHE_AT
    now = time.time()
    if (
        not force_refresh
        and _BULK_CACHE is not None
        and (now - _BULK_CACHE_AT) < _BULK_CACHE_TTL
    ):
        return _BULK_CACHE

    with _BULK_CACHE_LOCK:
        if (
            not force_refresh
            and _BULK_CACHE is not None
            and (time.time() - _BULK_CACHE_AT) < _BULK_CACHE_TTL
        ):
            return _BULK_CACHE

        ensure_waterlog_override_tables()
        bulk = {
            'periods': defaultdict(list),
            'daily': defaultdict(list),
            'np_overrides': defaultdict(dict),
            'spct_overrides': defaultdict(dict),
            'ps_overrides': defaultdict(dict),
        }
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT client_id, from_date, to_date, period_low, period_high, split_pct
                       FROM waterlog_periods ORDER BY client_id, from_date ASC'''
                )
                for row in cursor.fetchall():
                    bulk['periods'][row['client_id']].append(dict(row))

                cursor.execute(
                    'SELECT client_id, date, net_profit_complete FROM daily_watermarks ORDER BY client_id, date ASC'
                )
                for row in cursor.fetchall():
                    try:
                        d = datetime.strptime(row['date'], '%Y-%m-%d').date()
                        bulk['daily'][row['client_id']].append((d, float(row['net_profit_complete'])))
                    except Exception:
                        pass

                cursor.execute('SELECT client_id, from_date, amount FROM net_profit_overrides')
                for row in cursor.fetchall():
                    bulk['np_overrides'][row['client_id']][row['from_date']] = float(row['amount'])

                cursor.execute('SELECT client_id, from_date, pct FROM split_pct_overrides')
                for row in cursor.fetchall():
                    bulk['spct_overrides'][row['client_id']][row['from_date']] = float(row['pct'])

                cursor.execute('SELECT client_id, from_date, amount FROM profit_split_overrides')
                for row in cursor.fetchall():
                    bulk['ps_overrides'][row['client_id']][row['from_date']] = float(row['amount'])
        except Exception as e:
            logging.error(f"prefetch_waterlog_bulk failed: {e}")

        _BULK_CACHE = bulk
        _BULK_CACHE_AT = time.time()
        return bulk


def _override_maps_for_client(client_id, _bulk=None):
    if _bulk is not None:
        return (
            dict(_bulk['np_overrides'].get(client_id, {})),
            dict(_bulk['spct_overrides'].get(client_id, {})),
            dict(_bulk['ps_overrides'].get(client_id, {})),
        )
    return (
        get_net_profit_overrides(client_id),
        get_split_pct_overrides(client_id),
        get_profit_split_overrides(client_id),
    )


def canonical_client_stats_net(client_data) -> float | None:
    """Dashboard Stats net: payouts + hedging + farming + discrepancy - challenge_fees."""
    if not client_data or not isinstance(client_data, dict):
        return None
    stats = client_data.get('statistics') or {}
    cf = stats.get('cashflow_inprogress') if isinstance(stats.get('cashflow_inprogress'), dict) else {}
    hr = stats.get('hedging_review') if isinstance(stats.get('hedging_review'), dict) else {}
    if not cf:
        return None

    def _money(v):
        try:
            if v is None:
                return 0.0
            s = str(v).replace('$', '').replace(',', '').strip()
            return float(s) if s else 0.0
        except (TypeError, ValueError):
            return 0.0

    return round(
        _money(cf.get('payouts'))
        + _money(cf.get('hedging_results'))
        + _money(cf.get('farming_results'))
        + _money(hr.get('discrepancy'))
        - _money(cf.get('challenge_fees')),
        2,
    )


def _daily_watermarks_unreliable(vals):
    """
    Detect months where a lone positive end-of-period snapshot contradicts
    mostly-negative daily history (stale/inflated stats saved at midnight).
    """
    if len(vals) < 2:
        return False
    lo, hi = min(vals), max(vals)
    if hi <= 0 or lo >= 0:
        return False
    if hi - lo < 2500:
        return False
    neg = sum(1 for v in vals if v < -50)
    pos = sum(1 for v in vals if v > 50)
    return vals[-1] > 0 and neg >= max(3, pos * 2)


def _period_end_net_from_dailies(in_range, prev_period_net, *, period_complete, live_net=None):
    """Period-end net for profit-share rows; rejects unreliable watermark spikes."""
    if not in_range:
        return float(prev_period_net or 0.0)
    vals = [float(v) for (_, v) in in_range]
    if not period_complete and live_net is not None:
        return float(live_net)
    if _daily_watermarks_unreliable(vals):
        return min(vals)
    return vals[-1]


def _monthly_profit_split_amount(net_profit, last_net_at_split, split_pct):
    effective_base = max(float(last_net_at_split or 0.0), 0.0)
    if net_profit > effective_base and net_profit > 0:
        return (net_profit - effective_base) * float(split_pct) / 100.0
    return 0.0


def _compute_waterlog_monthly_from_daily(client_id, daily, last_net_at_split=0.0, prev_period_net=0.0, _bulk=None, _live_net=None):
    """
    Build Profit Share rows from daily_watermarks alone (no imported schedule).

    After the Mar 20 2026 transition: bi-monthly periods ending on the 15th
    and 30th (Feb uses last day of month).
    """
    from datetime import datetime as _dt, date as _date

    def _parse_money_cell(s):
        if s is None:
            return 0.0
        t = str(s).replace('$', '').replace(',', '').strip()
        if not t or t.lower() == 'nan':
            return 0.0
        try:
            return float(t)
        except ValueError:
            return 0.0

    def _fmt_date(d):
        return f"{d.month}/{d.day}/{d.year}"

    def _fmt_currency(v):
        if v < 0:
            return f"-${abs(v):,.2f}"
        return f"${v:,.2f}"

    TRANSITION_END = _date(2026, 3, 20)
    client_split_pct = get_client_split_pct(client_id)
    np_overrides, spct_overrides, ps_overrides = _override_maps_for_client(client_id, _bulk)

    result = []
    today = _dt.now().date()
    month_start = TRANSITION_END + timedelta(days=1)  # 3/21/2026

    for month_start, month_end in _iter_profit_split_periods(month_start, today):
        effective_end = min(month_end, today)
        in_range = [(d, v) for (d, v) in daily if month_start <= d <= effective_end]
        period_complete = effective_end >= month_end
        net_profit = _period_end_net_from_dailies(
            in_range,
            prev_period_net,
            period_complete=period_complete,
            live_net=_live_net,
        )

        monthly_np_key = _fmt_date(month_start)
        if monthly_np_key in np_overrides:
            net_profit = np_overrides[monthly_np_key]

        monthly_split_pct = client_split_pct
        if monthly_np_key in spct_overrides:
            monthly_split_pct = spct_overrides[monthly_np_key]

        profit_split = _monthly_profit_split_amount(net_profit, last_net_at_split, monthly_split_pct)

        result.append({
            'from_date':    _fmt_date(month_start),
            'to_date':      _fmt_date(month_end),
            'low':          _fmt_currency(net_profit),
            'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
            'split_pct':    monthly_split_pct,
        })

        if period_complete:
            prev_period_net = net_profit
            if profit_split > 0:
                last_net_at_split = net_profit

    if ps_overrides:
        for period in result:
            key = period['from_date']
            if key in ps_overrides:
                val = ps_overrides[key]
                period['profit_split'] = f"${val:,.0f}" if val > 0 else '$0'
                period['profit_split_override'] = True

    return {
        'periods': result,
        'last_split_net_profit': last_net_at_split,
    }


def compute_waterlog_from_db(client_id, _bulk=None, _live_net=None):
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
    Periods after 3/20/2026 are bi-monthly (end on the 15th and 30th; Feb uses
    last day of month):
      split = 50% of (current_net - net_at_last_paid_split) when current_net is
      above that baseline. The baseline only advances when a period actually
      pays a profit split (> 0); months with $0 split (e.g. drawdown) do not
      move the baseline. last_split_net_profit in the return dict is that baseline.
    """
    from datetime import datetime as _dt, date as _date

    def _parse_money_cell(s):
        if s is None:
            return 0.0
        t = str(s).replace('$', '').replace(',', '').strip()
        if not t or t.lower() == 'nan':
            return 0.0
        try:
            return float(t)
        except ValueError:
            return 0.0

    if _bulk is not None:
        periods_with_vals = list(_bulk['periods'].get(client_id, []))
        daily = list(_bulk['daily'].get(client_id, []))
    else:
        periods_with_vals = get_waterlog_periods_with_values(client_id)
        daily = get_all_daily_watermarks(client_id)

    # New clients: no imported sheet schedule — build monthly rows from daily data only.
    if not periods_with_vals:
        if not daily:
            return None
        return _compute_waterlog_monthly_from_daily(client_id, daily, _bulk=_bulk, _live_net=_live_net)

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

    np_overrides, spct_overrides, ps_overrides = _override_maps_for_client(client_id, _bulk)

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

    # Net at end of the most recent period that actually paid a split (split > 0).
    # Months with $0 split do not advance this — recoveries accrue from the last paid split.
    last_net_at_split = 0.0
    for row in result:
        if _parse_money_cell(row.get('profit_split')) > 0:
            last_net_at_split = _parse_money_cell(row.get('low'))

    # ── Bi-monthly periods from 3/21 onwards (ends on 15th / 30th) ─────
    prev_period_net = transition_net
    today = _dt.now().date()
    month_start = TRANSITION_END + timedelta(days=1)  # 3/21/2026

    for month_start, month_end in _iter_profit_split_periods(month_start, today):
        effective_end = min(month_end, today)

        in_range = [(d, v) for (d, v) in daily if month_start <= d <= effective_end]
        period_complete = effective_end >= month_end
        net_profit = _period_end_net_from_dailies(
            in_range,
            prev_period_net,
            period_complete=period_complete,
            live_net=_live_net,
        )

        # Apply net profit override for this monthly period
        monthly_np_key = _fmt_date(month_start)
        if monthly_np_key in np_overrides:
            net_profit = np_overrides[monthly_np_key]

        # Apply per-period split pct override
        monthly_split_pct = client_split_pct
        if monthly_np_key in spct_overrides:
            monthly_split_pct = spct_overrides[monthly_np_key]

        profit_split = _monthly_profit_split_amount(net_profit, last_net_at_split, monthly_split_pct)

        result.append({
            'from_date':    _fmt_date(month_start),
            'to_date':      _fmt_date(month_end),  # Always show full period end
            'low':          _fmt_currency(net_profit),
            'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
            'split_pct':    monthly_split_pct,
        })

        # Completed period: advance daily carry; baseline only moves when split was paid.
        if period_complete:
            prev_period_net = net_profit
            if profit_split > 0:
                last_net_at_split = net_profit

    # Net profit overrides are now applied during HWM calculation above
    # (no post-processing needed)

    if ps_overrides:
        for period in result:
            key = period['from_date']
            if key in ps_overrides:
                val = ps_overrides[key]
                period['profit_split'] = f"${val:,.0f}" if val > 0 else '$0'
                period['profit_split_override'] = True

    return {
        'periods': result,
        'last_split_net_profit': last_net_at_split,
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
