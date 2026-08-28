from dashboard.database import get_all_clients
from utils.data_processor import prop_firm_stats_parent
import re
from datetime import datetime, timedelta
import json
import functools
import time

# --- Simple In-Memory Cache to fix performance ---
class SimpleCache:
    def __init__(self, max_keys=50):
        self._cache = {}
        self._ttl = 300 # 5 minutes default
        self._max_keys = max_keys

    def get(self, key):
        if key in self._cache:
            data, expiry = self._cache[key]
            if time.time() < expiry:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key, value, ttl=None):
        # Evict expired entries first, then oldest if still over limit
        if len(self._cache) >= self._max_keys:
            self._evict()
        expiration = time.time() + (ttl or self._ttl)
        self._cache[key] = (value, expiration)

    def _evict(self):
        now = time.time()
        # Remove expired entries
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]
        # If still over limit, remove oldest entries
        while len(self._cache) >= self._max_keys:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    def clear(self):
        self._cache = {}


_overview_cache = SimpleCache(max_keys=50)


def clear_financial_overview_cache():
    """Invalidate cached financial overview results (e.g. after Super Admin stats exclusion saves)."""
    _overview_cache.clear()
    try:
        from dashboard.shared_cache import invalidate_prefix
        invalidate_prefix('super_admin_totals:')
        invalidate_prefix('super_admin_totals_summary:')
        invalidate_prefix('super_admin_totals_clients:')
        invalidate_prefix('super_admin_totals_bundle:')
        invalidate_prefix('super_admin_splits_bundle:')
        invalidate_prefix('super_admin_profit_splits:')
        invalidate_prefix('super_admin_avg_profit_splits:')
    except Exception:
        pass

def col_idx_to_letter(n):
    """
    Converts 0-based column index to Excel-style column letters.
    0 -> A, 1 -> B, 25 -> Z, 26 -> AA, 27 -> AB
    """
    res = ""
    while n >= 0:
        res = chr(ord('A') + (n % 26)) + res
        n = (n // 26) - 1
    return res


def cache_result(ttl=300):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create a cache key based on function name and arguments
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            cached = _overview_cache.get(key)
            if cached is not None:
                return cached
            
            result = func(*args, **kwargs)
            _overview_cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator

# --- Internal Data Access Helpers ---
# Wraps database calls to provide short-term caching within a request cycle or short period
@cache_result(ttl=10) 
def _get_cached_clients():
    """Cached wrapper for database.get_all_clients"""
    return get_all_clients()

# Public alias for external use
get_cached_clients_dataset = _get_cached_clients
# ------------------------------------------------

# --- Hierarchy-aware Profile Resolution ---
_hierarchy_profile_cache = {}
_hierarchy_profile_cache_time = 0

def _get_hierarchy_profile_map():
    """Build a {client_name: category} map from the hierarchy JSON (cached 60s)."""
    global _hierarchy_profile_cache, _hierarchy_profile_cache_time
    if _hierarchy_profile_cache and (time.time() - _hierarchy_profile_cache_time) < 60:
        return _hierarchy_profile_cache
    try:
        from config.hierarchy import SYSTEM_HIERARCHY
    except ImportError:
        return {}
    profile_map = {}
    if SYSTEM_HIERARCHY and 'admins' in SYSTEM_HIERARCHY:
        for admin_data in SYSTEM_HIERARCHY['admins'].values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    c_name = client.get('name')
                    cat = (client.get('category') or '').upper()
                    if c_name and cat:
                        profile_map[c_name] = cat
    _hierarchy_profile_cache = profile_map
    _hierarchy_profile_cache_time = time.time()
    return profile_map

def get_client_profile(client_id, identity=None):
    """Resolve client profile: check identity fields first, then hierarchy category, default PRIVATE."""
    if identity:
        p = (identity.get('profile') or identity.get('category') or identity.get('source') or '').upper()
        if p:
            return p
    # Fallback: check hierarchy
    h_map = _get_hierarchy_profile_map()
    real_name = identity.get('name') if identity else None
    if real_name and real_name in h_map:
        return h_map[real_name]
    if client_id in h_map:
        return h_map[client_id]
    return 'PRIVATE'
# ------------------------------------------------

def parse_currency(value_str):
    """
    Parses a currency string like "$120.65", "1,200.00", "-", "$ -" into a float.
    Returns 0.0 if the value is missing or represents zero.
    """
    if value_str is None:
        return 0.0
    if isinstance(value_str, (int, float)):
        return float(value_str)
        
    if not isinstance(value_str, str):
        return 0.0
    
    # Remove $ and , and spaces
    clean_str = value_str.replace('$', '').replace(',', '').strip()
    
    if not clean_str or clean_str in ['-', 'n/a', 'null']:
        return 0.0
        
    try:
        # Handle parentheses for negative numbers, e.g. (100) -> -100
        if clean_str.startswith('(') and clean_str.endswith(')'):
            return -float(clean_str[1:-1])
        return float(clean_str)
    except ValueError:
        return 0.0


P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FUNDED_HEDGE_COLS = [
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
    'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
]


def _date_in_range(dt, start_date=None, end_date=None):
    """Return True if dt falls within [start_date, end_date] (inclusive by calendar day)."""
    if not dt:
        return False
    d = dt.date() if hasattr(dt, 'date') else dt
    if start_date and d < start_date.date():
        return False
    if end_date and d > end_date.date():
        return False
    return True


def _eval_start_date(ev):
    return (
        parse_date(ev.get('Date Started'))
        or parse_date(ev.get('Date Purchased'))
        or parse_date(ev.get('Date'))
    )


def _eval_purchase_date(ev):
    return (
        parse_date(ev.get('Date Purchased'))
        or parse_date(ev.get('Date Started'))
        or parse_date(ev.get('Date'))
    )


def _eval_activation_date(ev):
    return (
        parse_date(ev.get('Date Started.1'))
        or parse_date(ev.get('Date Purchased'))
        or parse_date(ev.get('Date Started'))
        or parse_date(ev.get('Date'))
    )


def _eval_in_status_cohort(ev, start_date=None, end_date=None):
    """Account status/count metrics: cohort by eval start/purchase date when a range is set."""
    if not start_date and not end_date:
        return True
    eval_date = _eval_start_date(ev)
    if not eval_date:
        return True
    return _date_in_range(eval_date, start_date, end_date)


def _event_in_period(event_date, start_date=None, end_date=None):
    if not start_date and not end_date:
        return True
    return bool(event_date and _date_in_range(event_date, start_date, end_date))


def _sum_payouts_for_period(ev, start_date=None, end_date=None):
    """Sum payouts using the same rules as get_payouts_history (requires Date N)."""
    total = 0.0
    for i in range(1, 10):
        amt = parse_currency(ev.get(f'Payout {i}'))
        if amt <= 0:
            continue
        payout_date = parse_date(ev.get(f'Date {i}'))
        if not payout_date:
            continue
        if start_date or end_date:
            if not _date_in_range(payout_date, start_date, end_date):
                continue
        total += amt
    return total


def _fees_for_period(ev, start_date=None, end_date=None):
    fee = parse_currency(ev.get('Fee'))
    activation_fee = parse_currency(ev.get('Activation Fee'))
    if not start_date and not end_date:
        return fee, activation_fee
    counted_fee = 0.0
    counted_act = 0.0
    purchase_d = _eval_purchase_date(ev)
    if fee and purchase_d and _date_in_range(purchase_d, start_date, end_date):
        counted_fee = fee
    act_d = _eval_activation_date(ev)
    if activation_fee and act_d and _date_in_range(act_d, start_date, end_date):
        counted_act = activation_fee
    return counted_fee, counted_act


def _hedge_farming_for_period(ev, start_date=None, end_date=None,
                              p1_cols=None, funded_cols=None):
    p1_cols = p1_cols or P1_HEDGE_COLS
    funded_cols = funded_cols or FUNDED_HEDGE_COLS

    status_p1 = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status', '')).strip()

    p1_hedges = sum(parse_currency(ev.get(col)) for col in p1_cols)
    funded_hedges = sum(parse_currency(ev.get(col)) for col in funded_cols)
    farming_raw = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 61))

    hedge_results = 0.0
    farming_results = 0.0

    if status_p1:
        p1_d = parse_date(ev.get('Date Ended')) or parse_date(ev.get('Date Started'))
        if p1_hedges and _event_in_period(p1_d, start_date, end_date):
            hedge_results += p1_hedges

    if status_funded:
        fd_d = parse_date(ev.get('Date Ended.1')) or parse_date(ev.get('Date Started.1'))
        if funded_hedges and _event_in_period(fd_d, start_date, end_date):
            hedge_results += funded_hedges
        farm_d = parse_date(ev.get('Date Ended.1')) or parse_date(ev.get('Date Ended'))
        if farming_raw and _event_in_period(farm_d, start_date, end_date):
            farming_results = farming_raw

    return hedge_results, farming_results


def clear_financial_cache():
    """Invalidate the financial overview cache."""
    clear_financial_overview_cache()


def _portfolio_hedge_mt5_adjustment_vs_sheet_columns(
    clients_data, profile_filter=None, start_date=None, end_date=None
):
    """Sum of (live MT5 hedging P&L − sheet hedging+farming) per client.

    Mirrors get_client_performance_stats: for clients with MT5 deposits/balance and
    stored cashflow_inprogress hedge/farming totals, hedge displayed on cards uses
    live account math (including historical_accounts and prior_activity). Cumulative
    hedge/net charts are built from evaluation columns only; this delta aligns their
    endpoint with those statistics.

    Skips date-filtered and BEF-profile runs (same branches as perf stats).
    """
    if start_date or end_date:
        return 0.0
    if profile_filter and profile_filter.upper() == "BEF":
        return 0.0

    total_adj = 0.0
    for client_id, data in clients_data.items():
        if not data:
            continue
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get("identity", {})
            if get_client_profile(client_id, identity) != profile_filter.upper():
                continue

        stored_cf = (data.get("statistics") or {}).get("cashflow_inprogress") or {}
        if not stored_cf:
            continue
        h_r = stored_cf.get("hedging_results", 0) or 0
        f_r = stored_cf.get("farming_results", 0) or 0
        if h_r == 0 and f_r == 0:
            continue

        try:
            sheet_hedge = float(h_r) + float(f_r)
        except (TypeError, ValueError):
            sheet_hedge = 0.0

        acct = data.get("account") or {}
        hr = (data.get("statistics") or {}).get("hedging_review") or {}

        try:
            mt5_dep = float(acct.get("total_deposits") or 0)
        except (TypeError, ValueError):
            mt5_dep = 0.0
        try:
            mt5_bal = float(acct.get("balance") or 0)
        except (TypeError, ValueError):
            mt5_bal = 0.0
        try:
            mt5_with = float(acct.get("total_withdrawals") or 0)
        except (TypeError, ValueError):
            mt5_with = 0.0

        if mt5_dep == 0 and mt5_bal == 0:
            continue

        hist_dep_h = hist_with_h = hist_bal_h = 0.0
        prior_activity = 0.0
        try:
            prior_activity = float(hr.get("current_mt5_prior_activity") or 0)
        except (TypeError, ValueError):
            pass
        for ha in hr.get("historical_accounts") or []:
            try:
                hist_dep_h += float(ha.get("deposits", 0))
            except (TypeError, ValueError):
                pass
            try:
                hist_with_h += float(ha.get("withdrawals", 0))
            except (TypeError, ValueError):
                pass
            try:
                hist_bal_h += float(ha.get("final_balance", 0))
            except (TypeError, ValueError):
                pass
            try:
                prior_activity += float(ha.get("prior_activity_profit", 0))
            except (TypeError, ValueError):
                pass

        combined_dep = mt5_dep + hist_dep_h
        combined_with = mt5_with + hist_with_h
        combined_bal = mt5_bal + hist_bal_h
        live_actual = combined_bal - (combined_dep + combined_with) - prior_activity
        total_adj += live_actual - sheet_hedge

    return round(total_adj, 2)


@cache_result(ttl=30)
def calculate_all_financials(profile_filter=None, start_date=None, end_date=None):
    """
    Optimized aggregator that computes all financial metrics in a single pass.
    Returns a dictionary containing all necessary datasets for the dashboard.
    Optionally filters by start_date and end_date (datetime objects).
    """
    clients_data = _get_cached_clients()
    
    # Initialize containers
    overview = {}
    
    # Time-series containers (list of (date, amount))
    ts_payouts = []
    ts_net_profit = [] # Events for net profit (payouts, hedges, farming, -fees)
    ts_fees = []
    ts_hedge = []
    ts_farming = []
    
    # Deposits need special handling via deals
    # We will do deposits separately or integrate if feasible. 
    # For now, let's keep deposits separate or integrate if we process deals here too.
    # To maximize speed, let's process deals here too if possible.
    
    from collections import defaultdict
    deposits_daily = defaultdict(float)

    for client_id, data in clients_data.items():
        if not data: continue
        
        # --- Profile Filtering ---
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper():
                continue
        
        # --- 1. Process Evaluations (Sheet Data) ---
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue

            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            date_ended = parse_date(ev.get('Date Ended'))
            date_started_funded = parse_date(ev.get('Date Started.1'))
            date_ended_funded = parse_date(ev.get('Date Ended.1'))
            base_date = date_purchased or date_started or datetime.now()

            fee, activation_fee = _fees_for_period(ev, start_date, end_date)
            payouts = _sum_payouts_for_period(ev, start_date, end_date)
            hedge_results, farming_results = _hedge_farming_for_period(
                ev, start_date, end_date, P1_HEDGE_COLS, FUNDED_HEDGE_COLS
            )
            in_status_cohort = _eval_in_status_cohort(ev, start_date, end_date)

            # Prop Firm Overview Logic
            raw_prop_firm = ev.get('Prop Firm')
            if raw_prop_firm and raw_prop_firm != "-" and str(raw_prop_firm).lower() != "prop firm":
                prop_firm = prop_firm_stats_parent(normalize_prop_firm_name(raw_prop_firm))
                if not prop_firm:
                    continue

                has_financial = (
                    fee or activation_fee or payouts or hedge_results or farming_results
                )
                if not has_financial and not in_status_cohort:
                    continue
                
                if prop_firm not in overview:
                    overview[prop_firm] = {
                        "total_fees": 0.0,
                        "total_activation_fees": 0.0,
                        "total_payouts": 0.0,
                        "net": 0.0,
                        "account_count": 0,
                        "hedge_results": 0.0,
                        "farming_results": 0.0,
                        "active_accounts": 0,
                        "passed_accounts": 0,
                        "failed_accounts": 0,
                        "ended_count": 0,
                        "total_duration_days": 0,
                        "earliest_date": None,
                        "clients": set()
                    }

                status_p1 = str(ev.get('Status P1', '')).strip()
                status_funded = str(ev.get('Status', '')).strip()
                is_p1_fail = status_p1 == 'Fail'
                is_funded_fail = status_funded == 'Fail'
                is_funded_completed = status_funded == 'Completed'
                is_funded_ended = is_funded_fail or is_funded_completed
                is_in_progress = not is_p1_fail and not is_funded_ended
                is_passed_p1 = status_p1 == 'Pass' or status_p1.lower() == 'pass'
                
                target = overview[prop_firm]
                target["total_fees"] += fee
                target["total_activation_fees"] += activation_fee
                target["total_payouts"] += payouts
                target["hedge_results"] += hedge_results
                target["farming_results"] += farming_results
                if in_status_cohort:
                    target["account_count"] += 1
                    target["clients"].add(client_id)
                    if is_in_progress:
                        target["active_accounts"] += 1
                    if is_passed_p1:
                        target["passed_accounts"] += 1
                    if is_p1_fail or is_funded_fail:
                        target["failed_accounts"] += 1
                    if is_p1_fail or is_funded_ended:
                        target["ended_count"] += 1

                    duration = 0
                    if is_p1_fail:
                        s_d = parse_date(ev.get('Date Started'))
                        e_d = parse_date(ev.get('Date Ended'))
                        if s_d and e_d:
                            duration = (e_d - s_d).days
                    elif is_funded_ended:
                        s_d = parse_date(ev.get('Date Started'))
                        e_d = parse_date(ev.get('Date Ended.1'))
                        if s_d and e_d:
                            duration = (e_d - s_d).days

                    if duration > 0:
                        target["total_duration_days"] += duration

                    d_str = ev.get('Date Started') or ev.get('Date')
                    if d_str:
                        d_obj = parse_date(d_str)
                        if d_obj:
                            if target["earliest_date"] is None or d_obj < target["earliest_date"]:
                                target["earliest_date"] = d_obj

            # Time Series Logic
            def _ts_include(event_date):
                return _event_in_period(event_date, start_date, end_date)

            # 1. Fees (challenge fee vs activation fee may fall on different dates)
            if fee > 0:
                challenge_fee_date = date_purchased or base_date
                if _ts_include(challenge_fee_date):
                    ts_fees.append((challenge_fee_date, fee))
                    ts_net_profit.append((challenge_fee_date, -fee))
            if activation_fee > 0:
                activation_fee_date = date_started_funded or date_purchased or base_date
                if _ts_include(activation_fee_date):
                    ts_fees.append((activation_fee_date, activation_fee))
                    ts_net_profit.append((activation_fee_date, -activation_fee))

            # 2. Payouts (require Date N — same rule as Payout History)
            for i in range(1, 10):
                amt = parse_currency(ev.get(f'Payout {i}'))
                if amt <= 0:
                    continue
                d = parse_date(ev.get(f'Date {i}'))
                if not d:
                    continue
                if _ts_include(d):
                    ts_payouts.append((d, amt))
                    ts_net_profit.append((d, amt))
            
            # 3. Hedge Results
            p1_profit = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
            if p1_profit != 0:
                d = date_ended or date_started or base_date
                if _ts_include(d):
                    ts_hedge.append((d, p1_profit))
                    ts_net_profit.append((d, p1_profit))
            
            fd_profit = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
            if fd_profit != 0:
                d = date_ended_funded or date_started_funded or base_date
                if _ts_include(d):
                    ts_hedge.append((d, fd_profit))
                    ts_net_profit.append((d, fd_profit))

            # 4. Farming Results
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 61))
            if farming_calc != 0:
                d = date_ended_funded or date_ended or base_date
                if _ts_include(d):
                    ts_farming.append((d, farming_calc))
                    ts_net_profit.append((d, farming_calc))

        # --- 2. Process Deals (Deposits) ---
        deals_json = data.get('deals', '[]')
        try:
            deals = json.loads(deals_json) if isinstance(deals_json, str) else deals_json
        except:
            deals = []
            
        if deals:
            for deal in deals:
                d_time = deal.get('time_raw') or deal.get('time')
                if not d_time: continue
                
                try:
                    try:
                        dt = datetime.fromtimestamp(int(d_time))
                    except (ValueError, TypeError):
                        dt = datetime.fromisoformat(str(d_time))
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    continue
                
                # Date filtering for deals
                if start_date and dt.date() < start_date.date():
                    continue
                if end_date and dt.date() > end_date.date():
                    continue
                
                d_type = deal.get('type')
                def _f(val):
                    try: return float(val)
                    except: return 0.0
                profit = _f(deal.get('profit', 0))
                
                # Check for deposit
                is_balance = str(d_type) == '2' or str(d_type).upper() == 'BALANCE'
                if is_balance and profit > 0:
                     deposits_daily[date_str] += profit

    # Match statistics cards: MT5 Live Hedging Review vs sheet hedge+farming totals.
    hedge_mt5_adj = _portfolio_hedge_mt5_adjustment_vs_sheet_columns(
        clients_data, profile_filter=profile_filter, start_date=start_date, end_date=end_date
    )
    if abs(hedge_mt5_adj) >= 0.005:
        _adj_dt = datetime.now()
        ts_hedge.append((_adj_dt, hedge_mt5_adj))
        ts_net_profit.append((_adj_dt, hedge_mt5_adj))

    # --- Finalize Overview Data ---
    global_stats = {
        "net": 0.0,
        "ended": 0,
        "earliest": None,
        "expected_value": 0.0,
        "ev_per_day": 0.0,
        "total_duration": 0
    }

    for firm in overview:
        data = overview[firm]
        data["net"] = data["total_payouts"] + data["hedge_results"] + data["farming_results"] - (data["total_fees"] + data["total_activation_fees"])
        
        # Accumulate global
        global_stats["net"] += data["net"]
        global_stats["ended"] += data["ended_count"]
        global_stats["total_duration"] += data.get("total_duration_days", 0)
        
        if data.get("earliest_date"):
            if global_stats["earliest"] is None or data["earliest_date"] < global_stats["earliest"]:
                global_stats["earliest"] = data["earliest_date"]
        
        ended = data.get("ended_count", 0)
        data["expected_value"] = data["net"] / ended if ended > 0 else 0.0
        
        duration = data.get("total_duration_days", 0)
        data["ev_per_day"] = data["net"] / duration if duration > 0 else 0.0
        
        if "earliest_date" in data: del data["earliest_date"]
        if "total_duration_days" in data: del data["total_duration_days"]
        data["total_clients"] = len(data["clients"])
        del data["clients"]
        
    # Finalize Global Stats
    if global_stats["ended"] > 0:
        global_stats["expected_value"] = global_stats["net"] / global_stats["ended"]
        
    duration = global_stats.get("total_duration", 0)
    if duration > 0:
        global_stats["ev_per_day"] = global_stats["net"] / duration
        
    # Remove datetime object before return
    if "earliest" in global_stats: del global_stats["earliest"]
    if "total_duration" in global_stats: del global_stats["total_duration"]

    # --- Finalize Time Series ---
    from datetime import date as _date_type
    today_str = _date_type.today().strftime("%Y-%m-%d")

    def process_ts(events):
        if not events: return [], []
        events.sort(key=lambda x: x[0])
        from collections import defaultdict
        daily = defaultdict(float)
        for dt, val in events:
            day_str = dt.strftime("%Y-%m-%d")
            if day_str <= today_str:  # Exclude future dates
                daily[day_str] += val
        
        dates = []
        vals = []
        cum = 0.0
        for day in sorted(daily.keys()):
            cum += daily[day]
            dates.append(day)
            vals.append(cum)
        # Extend to current date so chart always ends at today
        if dates and dates[-1] < today_str:
            dates.append(today_str)
            vals.append(cum)
        return dates, vals
    
    # Process Deposits from simple dict
    def process_deposits_dict(d_dict):
        if not d_dict: return [], []
        dates = []
        vals = []
        cum = 0.0
        for day in sorted(d_dict.keys()):
            if day > today_str:  # Exclude future dates
                break
            cum += d_dict[day]
            dates.append(day)
            vals.append(cum)
        # Extend to current date so chart always ends at today
        if dates and dates[-1] < today_str:
            dates.append(today_str)
            vals.append(cum)
        return dates, vals

    payouts_dates, payouts_values = process_ts(ts_payouts)
    fees_dates, fees_values = process_ts(ts_fees)
    hedge_dates, hedge_values = process_ts(ts_hedge)
    farming_dates, farming_values = process_ts(ts_farming)
    net_dates, net_values = process_ts(ts_net_profit)
    dep_dates, dep_values = process_deposits_dict(deposits_daily)
    
    # Growth data usually refers to Net Profit (or Equity?)
    # In original: get_portfolio_growth_data was (Payouts - Fees) basically
    # But get_cumulative_trading_profit was the full net profit.
    # The chart allows selecting metric.
    # We will pass 'net_dates' as 'growth_dates' for default view.
    
    return {
        "overview": overview,
        "global_stats": global_stats,
        "payouts": (payouts_dates, payouts_values),
        "fees": (fees_dates, fees_values),
        "hedge": (hedge_dates, hedge_values),
        "farming": (farming_dates, farming_values),
        "net_profit": (net_dates, net_values),
        "deposits": (dep_dates, dep_values),
        "growth": (net_dates, net_values) # Default growth
    }

def normalize_prop_firm_name(name):
    """
    Normalizes prop firm names to merge duplicates.
    Example: "My Funded Futures" and "MyFundedFutures" become "My Funded Futures".
    Returns None for invalid/junk entries.
    """
    if not name:
        return None
        
    original = name.strip()
    normalized = original.lower().replace(" ", "").replace("_", "")
    
    # Skip junk/invalid entries (typos, single chars, generic labels)
    JUNK_NAMES = {'other', 'f', 'n/a', 'na', 'none', 'test', '-', ''}
    if normalized in JUNK_NAMES or len(normalized) <= 1:
        return None
    
    # Map normalized keys to display names
    MAPPING = {
        "myfundedfutures": "My Funded Futures",
        "myfundedfx": "My Funded Futures",
        "fundednext": "FundedNext",
        "fundednextflex": "FundedNext",
        "topstep": "Topstep",
        "topsteprtp": "TopStep RTP",
        "fundingticks": "Funding Ticks",
        "fundingtick": "Funding Ticks",
        "tradeday": "TradeDay",
        "tradeify": "Tradeify",
        "tradify": "Tradeify",
        "ftmo": "FTMO",
        "alphafutures": "Alpha Futures",
        "blueguardian": "Blue Guardian",
        "fundedtradingplus": "Funded Trading Plus",
        "the5ers": "The 5%ers",
        "5ers": "The 5%ers",
        "the5%ers": "The 5%ers",
        "apextraderfunding": "Apex Trader Funding",
        "apextrader": "Apex Trader Funding",
        "uprofittrader": "UProfit",
        "uprofit": "UProfit",
        "bulenox": "Bulenox",
        "tickticktrader": "TickTick Trader",
        "elitetraderfunding": "Elite Trader Funding",
        "take profit trader": "Take Profit Trader",
        "takeprofittrader": "Take Profit Trader",
        "toponefutures": "Top One Futures",
        "topone": "Top One Futures",
        "mff": "My Funded Futures",
        "mffu": "My Funded Futures",
        "mffuflex": "My Funded Futures",
        "fundedfuturesfamily": "Funded Futures Family",
        "fff": "Funded Futures Family",
        "lucid": "Lucid",
        "lucidmaxx": "LucidMaxx",
        "fundednextlegacyaccount": "FundedNext (Legacy)", # Keep distinct if wanted, or merge to FundedNext
    }
    
    # Direct match in mapping
    if normalized in MAPPING:
        return MAPPING[normalized]
        
    # Check if key starts with... (optional, logic for variations)
    if "myfundedfutures" in normalized:
        return "My Funded Futures"
    if "fundednextflex" in normalized:
        return "FundedNext"
    if "fundednext" in normalized:
        return "FundedNext"
    if "lucidmaxx" in normalized:
        return "LucidMaxx"
        
    # Fallback: Just return original if no mapping found, but title cased
    return original

def parse_date(date_str):
    """Parses date string to datetime object."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # Try MM/DD/YY
        return datetime.strptime(date_str.strip(), "%m/%d/%y")
    except ValueError:
        try:
            # Try YYYY-MM-DD
            return datetime.strptime(date_str.strip(), "%Y-%m-%d")
        except ValueError:
            return None

def get_payouts_history(start_date=None, end_date=None, prop_firm_filter=None, profile_filter=None):
    """
    Returns a list of all payouts with details.
    """
    # Import hierarchy to map clients to traders/admins
    try:
        from config.hierarchy import SYSTEM_HIERARCHY
    except ImportError:
        import sys, os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config.hierarchy import SYSTEM_HIERARCHY

    # Build client map: {client_name: {'trader': T, 'admin': A}}
    client_map = {}
    if SYSTEM_HIERARCHY and 'admins' in SYSTEM_HIERARCHY:
        for admin_name, admin_data in SYSTEM_HIERARCHY['admins'].items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    c_name = client.get('name')
                    if c_name:
                        client_map[c_name] = {
                            'admin': admin_name,
                            'trader': trader_name
                        }

    clients_data = _get_cached_clients()
    payouts_list = []
    
    for client_id, data in clients_data.items():
        if not data:
            continue
            
        # Get Client Metadata
        identity = data.get('identity', {})
        real_client_name = identity.get('name') or client_id
        
        # Get hierarchy info
        h_info = client_map.get(real_client_name) or client_map.get(client_id)
        admin_name = h_info['admin'] if h_info else "-"
        trader_name = h_info['trader'] if h_info else "-"

        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            c_prof = get_client_profile(client_id, identity)
            if c_prof != profile_filter.upper():
                continue

        evaluations = data.get('evaluations', [])
        for eval_data in evaluations:
            if not isinstance(eval_data, dict):
                continue
            prop_firm = eval_data.get('Prop Firm')
            if not prop_firm or prop_firm == "-": continue
            
            prop_firm = prop_firm_stats_parent(normalize_prop_firm_name(prop_firm))
            if not prop_firm: continue
            
            # Apply prop firm filter if provided
            if prop_firm_filter and prop_firm != prop_firm_filter:
                continue
                
            account_num = eval_data.get('Account #') or eval_data.get('Account #.1') or '-'
            
            # Check Payout 1..10
            for i in range(1, 10):
                p_key = f'Payout {i}'
                d_key = f'Date {i}' # Assuming 'Date 1', 'Date 2' etc matches Payout
                
                amount = parse_currency(eval_data.get(p_key))
                if amount > 0:
                    date_str = eval_data.get(d_key)
                    date_obj = parse_date(date_str)
                    
                    if date_obj:
                        # Filter check
                        if start_date and date_obj < start_date:
                            continue
                        if end_date and date_obj > end_date:
                            continue
                            
                        payouts_list.append({
                            "date": date_obj,
                            "date_str": date_str, 
                            "prop_firm": prop_firm,
                            "amount": amount,
                            "client_name": real_client_name,
                            "admin_name": admin_name,
                            "trader_name": trader_name,
                            "account_id": account_num,
                            # Keep old keys for safety if used elsewhere
                            "client": client_id,
                            "account": account_num
                        })
    
    # Sort by date desc
    payouts_list.sort(key=lambda x: x['date'], reverse=True)
    return payouts_list

@cache_result(ttl=300)
def get_payouts_growth_data(profile_filter=None):
    """
    Calculates cumulative payouts over time (ignoring fees).
    Returns lists of labels (dates) and data points (cumulative payouts).
    """
    clients_data = _get_cached_clients()
    events = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Payouts Only
            for i in range(1, 10):
                date_str = ev.get(f'Date {i}')
                amount = parse_currency(ev.get(f'Payout {i}'))
                if amount > 0 and date_str:
                    date_obj = parse_date(date_str)
                    if date_obj:
                        events.append((date_obj, amount))
    
    # Sort events by date
    events.sort(key=lambda x: x[0])
    
    if not events:
        return [], []
        
    dates = []
    values = []
    cumulative = 0.0
    
    from collections import defaultdict
    daily_changes = defaultdict(float)
    
    for date_obj, amount in events:
        date_str = date_obj.strftime("%Y-%m-%d")
        daily_changes[date_str] += amount
        
    sorted_days = sorted(daily_changes.keys())
    
    for day in sorted_days:
        cumulative += daily_changes[day]
        dates.append(day)
        values.append(cumulative)
        
    return dates, values

def get_mt5_deals_data(profile_filter=None):
    """
    Helper to get processed daily changes for deposits and trading profit.
    Returns (deposits_daily, profit_daily) dicts: {date_str: amount}
    """
    clients_data = _get_cached_clients()
    
    from collections import defaultdict
    deposits_daily = defaultdict(float)
    profit_daily = defaultdict(float)
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper(): continue
            
        deals_json = data.get('deals', '[]')
        try:
            deals = json.loads(deals_json) if isinstance(deals_json, str) else deals_json
        except:
            deals = []
            
        if not deals: continue
        
        for deal in deals:
            # MT5 deal structure: {'time': epoch, 'type': int, 'profit': float, 'swap': float, 'commission': float, ...}
            d_time = deal.get('time_raw') or deal.get('time')
            if not d_time: continue
                
            try:
                try:
                    dt = datetime.fromtimestamp(int(d_time))
                except (ValueError, TypeError):
                    dt = datetime.fromisoformat(str(d_time))
                date_str = dt.strftime("%Y-%m-%d")
            except:
                continue
                
            def _f(val):
                try: return float(val)
                except: return 0.0
            
            d_type = deal.get('type')
            profit = _f(deal.get('profit', 0))
            swap = _f(deal.get('swap', 0))
            comm = _f(deal.get('commission', 0))
            
            # Type 2 is usually BALANCE (Deposits/Withdrawals)
            is_balance = str(d_type) == '2' or str(d_type).upper() == 'BALANCE'
            
            if is_balance:
                # If profit > 0, it's a deposit. If < 0, it's a withdrawal.
                # User asked to track "Deposits".
                if profit > 0:
                    deposits_daily[date_str] += profit
            else:
                # Trading Profit
                trading_profit = profit + swap + comm
                profit_daily[date_str] += trading_profit
                
    return deposits_daily, profit_daily

@cache_result(ttl=300)
def get_cumulative_deposits(profile_filter=None):
    """Calculates cumulative deposits over time."""
    deposits_daily, _ = get_mt5_deals_data(profile_filter)
    if not deposits_daily: return [], []
    
    dates = []
    values = []
    cumulative = 0.0
    sorted_days = sorted(deposits_daily.keys())
    
    for day in sorted_days:
        cumulative += deposits_daily[day]
        dates.append(day)
        values.append(cumulative)
        
    return dates, values

def parse_date(date_str):
    """Parses date string to datetime object."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # Try common formats
        for fmt in ["%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None
    except:
        return None

@cache_result(ttl=300)
def get_cumulative_trading_profit(profile_filter=None):
    """
    Calculates cumulative Net Profit over time based on Payouts, Hedge Results, Farming, and Fees.
    Uses Evaluation data (Sheet) to match the Summary Card 'Net Profit'.
    """
    clients_data = _get_cached_clients()
    events = [] # (datetime, amount)
    
    # Columns definition matching calculate_propfirm_overview
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    for client_id, data in clients_data.items():
        if not data: continue
        
        # Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Match filtering logic from calculate_propfirm_overview
            raw_prop_firm = ev.get('Prop Firm')
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue

            # Extract Dates
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            date_ended = parse_date(ev.get('Date Ended'))
            date_started_funded = parse_date(ev.get('Date Started.1'))
            date_ended_funded = parse_date(ev.get('Date Ended.1'))
            
            # Default date fallback logic
            # If we have a cost/revenue but no specific date, place it at the closest known date
            base_date = date_purchased or date_started or datetime.now()
            
            # 1. Fees (Negative)
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            total_fee = fee + act_fee
            if total_fee > 0:
                events.append((date_purchased or base_date, -total_fee))
                
            # 2. Payouts (Positive)
            for i in range(1, 10):
                d_str = ev.get(f'Date {i}')
                amt = parse_currency(ev.get(f'Payout {i}'))
                if amt != 0:
                    d = parse_date(d_str)
                    events.append((d or base_date, amt))
                    
            # 3. Hedge Results P1
            p1_profit = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
            if p1_profit != 0:
                # Assign to Date Ended or Date Started
                events.append((date_ended or date_started or base_date, p1_profit))
                
            # 4. Funded Hedge Results
            fd_profit = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
            if fd_profit != 0:
                # Assign to Date Ended Funded or Date Started Funded
                events.append((date_ended_funded or date_started_funded or base_date, fd_profit))
                
            # 5. Farming Results
            # Match calculate_propfirm_overview logic: Sum of Hedge Day 1-50
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 61))
            
            if farming_calc != 0:
                # Assign to later dates
                events.append((date_ended_funded or date_ended or base_date, farming_calc))
    
    if not events:
        return [], []
        
    # Sort events by date
    events.sort(key=lambda x: x[0])
    
    # Aggregate by day
    from collections import defaultdict
    daily_changes = defaultdict(float)
    
    for dt, val in events:
        d_str = dt.strftime("%Y-%m-%d")
        daily_changes[d_str] += val
        
    dates = []
    values = []
    cumulative = 0.0
    sorted_days = sorted(daily_changes.keys())
    
    for day in sorted_days:
        cumulative += daily_changes[day]
        dates.append(day)
        values.append(cumulative)
        
    return dates, values

@cache_result(ttl=300)
def get_portfolio_growth_data(profile_filter=None):
    """
    Calculates cumulative portfolio growth over time.
    Returns lists of labels (dates) and data points (net profit).
    """
    clients_data = _get_cached_clients()
    
    # Store all financial events: (date, amount)
    events = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # 1. Payouts (Positive)
            for i in range(1, 10):
                date_str = ev.get(f'Date {i}')
                amount = parse_currency(ev.get(f'Payout {i}'))
                if amount > 0 and date_str:
                    date_obj = parse_date(date_str)
                    if date_obj:
                        events.append((date_obj, amount))
            
            # 2. Fees (Negative) - Use "Date Paid" or similar if available, else approximate?
            # Many sheets don't have fee dates. We might need to omit fees from the *timeline* 
            # if we don't have dates, or assume they happened at account start?
            # For this request, let's focus on Payouts for growth, or Net Profit if we can find dates.
            # Without dates for Fees/Hedges, a true "Net Profit Over Time" is hard.
            # Let's try to find dates for Hedges/Farming.
            
            purchase_date_str = ev.get('Date')
            purchase_date = parse_date(purchase_date_str)
            
            if purchase_date:
                # Add Fees at purchase date
                fee = parse_currency(ev.get('Fee'))
                act_fee = parse_currency(ev.get('Activation Fee'))
                total_fee = fee + act_fee
                if total_fee > 0:
                    events.append((purchase_date, -total_fee))
                    
                # Add Hedge Results? We don't have dates for each hedge result usually...
                # We can assume they happen "after" purchase. 
                # For now, let's stick to (Payouts - Fees) which has dates.
                
    # Sort events by date
    events.sort(key=lambda x: x[0])
    
    if not events:
        return [], []
        
    dates = []
    values = []
    cumulative = 0.0
    
    # Aggregate by day
    from collections import defaultdict
    daily_changes = defaultdict(float)
    
    for date_obj, amount in events:
        date_str = date_obj.strftime("%Y-%m-%d")
        daily_changes[date_str] += amount
        
    sorted_days = sorted(daily_changes.keys())
    
    for day in sorted_days:
        cumulative += daily_changes[day]
        dates.append(day)
        values.append(cumulative)
        
    return dates, values

@cache_result(ttl=300)
def calculate_propfirm_overview(profile_filter=None):
    """
    Aggregates financial data by Prop Firm.
    Returns a dictionary.
    """
    clients_data = _get_cached_clients() # Returns {client_id: full_data_dict}
    
    overview = {}
    
    # Define columns for calculations
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
    # Hedge Day 1 to 60
    
    for client_id, data in clients_data.items():
        if not data:
            continue

        # Filter by Profile if profile_filter is provided
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper():
                continue
            
        evaluations = data.get('evaluations', [])
        if not evaluations:
            continue
            
        for eval_data in evaluations:
            if not isinstance(eval_data, dict):
                continue
            raw_prop_firm = eval_data.get('Prop Firm')
            
            # Skip if no prop firm name or if it's header/invalid
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue
                
            # Normalize Name (TopStep RTP rolls up into Topstep for totals)
            prop_firm = prop_firm_stats_parent(normalize_prop_firm_name(raw_prop_firm))
            if not prop_firm:
                continue
            
            if prop_firm not in overview:
                overview[prop_firm] = {
                    "total_fees": 0.0,
                    "total_activation_fees": 0.0,
                    "total_payouts": 0.0,
                    "net": 0.0,
                    "account_count": 0,
                    "hedge_results": 0.0,
                    "farming_results": 0.0,
                    "active_accounts": 0,
                    "passed_accounts": 0,
                    "failed_accounts": 0,
                    "ended_count": 0,
                    "earliest_date": None,
                    "clients": set()
                }
            
            # === Financials ===
            # Fee is OUTFLOW, so we treat it as positive cost.
            # When calculating Net Profit, we subtract it.
            fee = parse_currency(eval_data.get('Fee'))
            activation_fee = parse_currency(eval_data.get('Activation Fee'))
            
            # Payouts (INFLOW) — dated payouts only, matching Payout History
            payouts = _sum_payouts_for_period(eval_data)
            
            # Hedge Results (PROFIT/LOSS)
            p1_hedges = sum(parse_currency(eval_data.get(col)) for col in P1_HEDGE_COLS)
            funded_hedges = sum(parse_currency(eval_data.get(col)) for col in FUNDED_HEDGE_COLS)
            
            # Farming Results (PROFIT)
            farming_results = 0.0
            for i in range(1, 61):
                key = f'Hedge Day {i}'
                farming_results += parse_currency(eval_data.get(key))
            
            # === Status ===
            status_p1 = str(eval_data.get('Status P1', '')).strip()
            status_funded = str(eval_data.get('Status', '')).strip()
            status_p1_lower = status_p1.lower()
            status_funded_lower = status_funded.lower()
            
            # Only count hedge/farming for rows with a populated status
            hedge_results = 0.0
            if status_p1:
                hedge_results += p1_hedges
            if status_funded:
                hedge_results += funded_hedges
            if not status_funded:
                farming_results = 0.0
            
            # Logic from data_processor.py
            is_p1_fail = status_p1 == 'Fail'
            is_funded_fail = status_funded == 'Fail'
            is_funded_completed = status_funded == 'Completed'
            is_funded_ended = is_funded_fail or is_funded_completed
            is_in_progress = not is_p1_fail and not is_funded_ended
            
            is_passed_p1 = status_p1 == 'Pass' or status_p1_lower == 'pass'
            
            # Update counts
            if is_in_progress:
                overview[prop_firm]["active_accounts"] += 1
            
            if is_passed_p1:
                overview[prop_firm]["passed_accounts"] += 1
                
            if is_p1_fail or is_funded_fail:
                overview[prop_firm]["failed_accounts"] += 1
                
            if is_p1_fail or is_funded_ended:
                overview[prop_firm]["ended_count"] += 1
                
            # Date tracking
            d_str = eval_data.get('Date Started') or eval_data.get('Date')
            if d_str:
                d_obj = parse_date(d_str)
                if d_obj:
                     cur_earliest = overview[prop_firm]["earliest_date"]
                     if cur_earliest is None or d_obj < cur_earliest:
                         overview[prop_firm]["earliest_date"] = d_obj
            
            # Update totals (accumulate)
            overview[prop_firm]["total_fees"] += fee
            overview[prop_firm]["total_activation_fees"] += activation_fee
            overview[prop_firm]["total_payouts"] += payouts
            overview[prop_firm]["hedge_results"] += hedge_results
            overview[prop_firm]["farming_results"] += farming_results
            overview[prop_firm]["account_count"] += 1
            overview[prop_firm]["clients"].add(client_id)
            
    # Finalize calculations
    for firm in overview:
        data = overview[firm]
        # Net Profit = Payouts + Hedge Results + Farming Results - (Fees + Activation Fees)
        data["net"] = data["total_payouts"] + data["hedge_results"] + data["farming_results"] - (data["total_fees"] + data["total_activation_fees"])
        
        # EV
        ended = data.get("ended_count", 0)
        data["expected_value"] = data["net"] / ended if ended > 0 else 0.0
        
        # EV Per Day
        data["ev_per_day"] = 0.0
        if data.get("earliest_date"):
            days = (datetime.now() - data["earliest_date"]).days
            if days > 0:
                data["ev_per_day"] = data["net"] / days
        
        # Clean up objects not serializable
        if "earliest_date" in data:
            del data["earliest_date"]

        # Convert set to count
        data["total_clients"] = len(data["clients"])
        del data["clients"]
        
    return overview

def get_cumulative_fees_data(profile_filter=None):
    """Calculates cumulative fees (Fees + Activation) over time."""
    clients_data = _get_cached_clients()
    events = [] # (datetime, amount)
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = get_client_profile(client_id, identity)
            if client_profile != profile_filter.upper(): continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # 1. Fees (Negative, but usually shown as positive 'Spent' on card. 
            # Graph should likely show cumulative SPEND (positive slope) or cumulative CASHFLOW (negative slope)?
            # The card says "Total Fees Spent: $1.1M". Correct graph would probably be strictly increasing cost.
            # But "Net Profit" graph subtracts it.
            # Let's show it as Positive Cumulative Cost for the "Total Fees Spent" graph.
            
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            total_fee = fee + act_fee
            
            if total_fee > 0:
                date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
                date_started = parse_date(ev.get('Date Started'))
                base_date = date_purchased or date_started or datetime.now()
                events.append((base_date, total_fee)) # Positive value = Total Spent

    return _aggregate_events_cumulative(events)

def get_cumulative_hedge_data(profile_filter=None):
    """Calculates cumulative hedge results over time."""
    clients_data = _get_cached_clients()
    events = [] 
    
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    for client_id, data in clients_data.items():
        if not data: continue
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            cp = get_client_profile(client_id, identity)
            if cp != profile_filter.upper(): continue
            
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Dates
            date_started = parse_date(ev.get('Date Started'))
            date_ended = parse_date(ev.get('Date Ended'))
            date_started_funded = parse_date(ev.get('Date Started.1'))
            date_ended_funded = parse_date(ev.get('Date Ended.1'))
            base_date = date_started or datetime.now()

            # P1 Hedges
            p1_profit = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
            if p1_profit != 0:
                events.append((date_ended or date_started or base_date, p1_profit))
            
            # Funded Hedges
            fd_profit = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
            if fd_profit != 0:
                events.append((date_ended_funded or date_started_funded or base_date, fd_profit))

    hedge_mt5_adj = _portfolio_hedge_mt5_adjustment_vs_sheet_columns(
        clients_data, profile_filter=profile_filter, start_date=None, end_date=None
    )
    if abs(hedge_mt5_adj) >= 0.005:
        events.append((datetime.now(), hedge_mt5_adj))

    return _aggregate_events_cumulative(events)

def get_cumulative_farming_data(profile_filter=None):
    """Calculates cumulative farming results over time."""
    clients_data = _get_cached_clients()
    events = [] 
    
    for client_id, data in clients_data.items():
        if not data: continue
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            cp = get_client_profile(client_id, identity)
            if cp != profile_filter.upper(): continue
            
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Dates
            date_started = parse_date(ev.get('Date Started'))
            date_ended = parse_date(ev.get('Date Ended'))
            date_ended_funded = parse_date(ev.get('Date Ended.1'))
            base_date = date_started or datetime.now()

            # Farming Results
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 61))
            if farming_calc != 0:
                events.append((date_ended_funded or date_ended or base_date, farming_calc))
                
    return _aggregate_events_cumulative(events)

def _aggregate_events_cumulative(events):
    if not events:
        return [], []
        
    events.sort(key=lambda x: x[0])
    
    from collections import defaultdict
    daily_changes = defaultdict(float)
    
    for dt, val in events:
        d_str = dt.strftime("%Y-%m-%d")
        daily_changes[d_str] += val
        
    dates = []
    values = []
    cumulative = 0.0
    sorted_days = sorted(daily_changes.keys())
    
    for day in sorted_days:
        cumulative += daily_changes[day]
        dates.append(day)
        values.append(cumulative)
        
    return dates, values

def calculate_trader_stats(profile_filter=None):
    """Calculates aggregated statistics per trader."""
    clients_data = _get_cached_clients()
    traders_stats = {}
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        identity = data.get('identity', {})
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            c_prof = get_client_profile(client_id, identity)
            if c_prof != profile_filter.upper():
                continue

        trader_name = identity.get('trader_name', 'Unassigned')
        trader_name = identity.get('trader')
        
        if not trader_name or str(trader_name).strip().lower() in ['none', 'null', '', '-']:
            trader_name = "Unassigned"
            
        if trader_name not in traders_stats:
            traders_stats[trader_name] = {
                "name": trader_name,
                "sheets_reviewed": 0,
                "client_count": 0,
                "total_payouts": 0.0,
                "total_negative_hedge": 0.0,
                "negative_hedge_details": [],
                "farming_days_count": 0,
                "farming_missing_notes": 0,
                "farming_warnings": []
            }
        
        stats = traders_stats[trader_name]
        stats['client_count'] += 1
        stats['sheets_reviewed'] += 1
        
        evaluations = data.get('evaluations', [])
        for idx, ev in enumerate(evaluations):
            if not isinstance(ev, dict):
                continue
            row_num = idx + 3 # Matches frontend assumption (Row 3 start)
            acc_num = ev.get('Account #') or ev.get('Account #.1') or 'Unknown'
            # Payouts 1-10
            for i in range(1, 11):
                val = ev.get(f'Payout {i}')
                amt = parse_currency(val) if val else 0.0
                if amt > 0: stats['total_payouts'] += amt
            
            # Negative Hedge Logic
            
            # Helper to check if any hedging occurred
            def has_hedging_activity(ev_data, prefix="Hedge Result", count=5):
                for k in range(1, count + 1):
                    val = parse_currency(ev_data.get(f"{prefix} {k}"))
                    if val != 0: return True
                return False

            # 1. Phase 1 Net (Column N)
            p1_net = parse_currency(ev.get('Hedge Net'))
            
            # Only count negative hedge net if actual hedging results exist (not just fees)
            if p1_net < -1.0 and has_hedging_activity(ev, "Hedge Result", 5):
                stats['total_negative_hedge'] += p1_net
                
                date_str = ev.get('Date Ended') or ev.get('Date')
                date_obj = parse_date(date_str)
                date_iso = date_obj.strftime("%Y-%m-%d") if date_obj else ""
                
                stats['negative_hedge_details'].append({
                    "client": client_id,
                    "account": acc_num,
                    "amount": p1_net,
                    "link": f"/dashboard/{client_id}?range=N{row_num}",
                    "date": date_iso
                })

            # 2. Funded Net (Column AA)
            fd_net = parse_currency(ev.get('Hedge Net.1'))
            
            # Check Funded Hedge Results (1.1, 2.1, etc)
            funded_hedged = False
            # Check 1.1 explicitly
            if parse_currency(ev.get("Hedge Result 1.1")) != 0: funded_hedged = True
            # Check 2.1 - 5.1
            if not funded_hedged:
                for k in range(2, 6):
                    if parse_currency(ev.get(f"Hedge Result {k}.1")) != 0: 
                        funded_hedged = True
                        break

            if fd_net < -1.0 and funded_hedged:
                stats['total_negative_hedge'] += fd_net
                
                date_str = ev.get('Date Ended.1')
                date_obj = parse_date(date_str)
                date_iso = date_obj.strftime("%Y-%m-%d") if date_obj else ""
                
                stats['negative_hedge_details'].append({
                    "client": client_id,
                    "account": acc_num,
                    "amount": fd_net,
                    "link": f"/dashboard/{client_id}?range=AA{row_num}",
                    "date": date_iso
                })
            
            
            # Farming Logic
            for d in range(1, 61):
                h_val = parse_currency(ev.get(f'Hedge Day {d}'))
                if h_val != 0:
                    stats['farming_days_count'] += 1
                    
                    p_val_raw = ev.get(f'Day {d} Profit')
                    if not p_val_raw or str(p_val_raw).strip() in ['', '-']:
                        stats['farming_missing_notes'] += 1
                        
                        # Calculate Prop Day Col
                        # Prop Day 1 = AK (Index 36)
                        # Prop Day 2 = AM (Index 38)
                        col_idx = 36 + (d - 1) * 2
                        col_let = col_idx_to_letter(col_idx)
                        
                        stats['farming_warnings'].append({
                            "client": client_id,
                            "day": d,
                            "link": f"/dashboard/{client_id}?range={col_let}{row_num}"
                        })

    return list(traders_stats.values())


def aggregate_super_admin_totals(clients):
    """Sum per-client performance rows into Super Admin stat-card totals."""
    t_pay = sum(c.get('payouts', 0) for c in clients)
    t_dep = sum(c.get('deposits', 0) for c in clients)
    t_fees = sum(c.get('fees', 0) for c in clients)
    t_net = sum(c.get('net_profit', 0) for c in clients)
    t_hedge = sum(c.get('hedge_profit', 0) for c in clients)
    t_farming = sum(c.get('farming_profit', 0) for c in clients)
    t_active = sum(c.get('active', 0) for c in clients)
    t_passed = sum(c.get('passed', 0) for c in clients)
    t_failed = sum(c.get('failed', 0) for c in clients)
    t_ended = sum(c.get('ended', 0) for c in clients)
    t_duration = sum(c.get('total_duration_days', 0) for c in clients)

    ev = t_net / t_ended if t_ended > 0 else 0.0
    ev_day = t_net / t_duration if t_duration > 0 else 0.0
    return {
        'total_payouts': round(t_pay, 2),
        'total_deposits': round(t_dep, 2),
        'total_fees': round(t_fees, 2),
        'total_net_profit': round(t_net, 2),
        'active_accounts': t_active,
        'completed_accounts': t_passed,
        'failed_accounts': t_failed,
        'total_hedge': round(t_hedge, 2),
        'total_farming': round(t_farming, 2),
        'expected_value': round(ev, 2),
        'ev_per_day': round(ev_day, 2),
    }


def build_super_admin_totals_summary(profile_filter=None, excluded_clients=None):
    """Aggregate Super Admin stat cards from the same per-client stats as the breakdown table."""
    excluded = {str(x).strip() for x in (excluded_clients or []) if x is not None and str(x).strip()}
    clients = get_client_performance_stats(profile_filter)
    clients = [c for c in clients if str(c.get('client_id') or '').strip() not in excluded]
    return aggregate_super_admin_totals(clients)


@cache_result(ttl=300)
def get_client_performance_stats(profile_filter=None, start_date=None, end_date=None):
    """
    Returns a list of per-client performance statistics.
    Used for the Client Performance Table.
    Optionally filters by start_date and end_date (datetime objects).
    """
    # BEF hidden firms — evaluations from these firms are excluded for BEF view
    BEF_HIDDEN_FIRMS = {'lucid', 'apex', 'tradeday', 'toponefutures', 'fundedfuturesfamily', 'fff', 'the5ers', 'the5%ers'}
    is_bef = profile_filter and profile_filter.upper() == 'BEF'

    def _is_firm_hidden(firm_name):
        if not is_bef:
            return False
        return (firm_name or '').strip().lower().replace(' ', '') in BEF_HIDDEN_FIRMS
    # Import hierarchy to map clients to traders/admins
    try:
        from config.hierarchy import SYSTEM_HIERARCHY
    except ImportError:
        import sys, os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config.hierarchy import SYSTEM_HIERARCHY

    # Build client map
    client_map = {}
    if SYSTEM_HIERARCHY and 'admins' in SYSTEM_HIERARCHY:
        for admin_name, admin_data in SYSTEM_HIERARCHY['admins'].items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    c_name = client.get('name')
                    if c_name:
                        client_map[c_name] = {
                            'admin': admin_name,
                            'trader': trader_name,
                            'category': (client.get('category') or '').upper()
                        }

    clients_data = _get_cached_clients()
    clients_list = []

    for client_id, data in clients_data.items():
        if not data: continue
        
        identity = data.get('identity', {})
        real_client_name = identity.get('name') or client_id
        
        # Profile Filter — check identity first, then hierarchy category as fallback
        source = get_client_profile(client_id, identity)
        
        if profile_filter and profile_filter.upper() != "ALL":
            if source != profile_filter.upper():
                continue
                
        # Hierarchy Info
        h_info = client_map.get(real_client_name) or client_map.get(client_id)
        admin_name = h_info['admin'] if h_info else "-"
        trader_name = h_info['trader'] if h_info else "-"

        # Init Stats
        c_stats = {
            "client_id": real_client_name,
            "trader": trader_name,
            "admin": admin_name,
            "source": source,
            "payouts": 0.0,
            "deposits": 0.0,
            "fees": 0.0,
            "net_profit": 0.0,
            "active": 0,
            "passed": 0,
            "failed": 0,
            "hedge_profit": 0.0,
            "farming_profit": 0.0,
            "ended": 0,
            "total_duration_days": 0
        }
        
        # 1. Evaluations Payouts/Fees/Status
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Skip hidden firms for BEF view
            if _is_firm_hidden(ev.get('Prop Firm')):
                continue

            in_status_cohort = _eval_in_status_cohort(ev, start_date, end_date)
            fee, act_fee = _fees_for_period(ev, start_date, end_date)
            c_stats['fees'] += fee + act_fee
            c_stats['payouts'] += _sum_payouts_for_period(ev, start_date, end_date)

            if not in_status_cohort:
                continue

            # Status logic expanded
            status_p1_raw = str(ev.get('Status P1') or '').strip()
            status_funded_raw = str(ev.get('Status') or '').strip()
            status = status_funded_raw.lower()
            if 'passed' in status or 'funded' in status:
                c_stats['passed'] += 1
            elif 'failed' in status or 'breached' in status or 'blown' in status or 'fail' in status:
                c_stats['failed'] += 1
            elif 'active' in status or 'phase' in status or 'running' in status or 'ongoing' in status or 'trading' in status or 'challenge' in status:
                c_stats['active'] += 1

            # Ended count & duration for EV calculation
            is_p1_fail = status_p1_raw == 'Fail'
            is_funded_fail = status_funded_raw == 'Fail'
            is_funded_completed = status_funded_raw == 'Completed'
            if is_p1_fail or is_funded_fail or is_funded_completed:
                c_stats['ended'] += 1
                s_d = parse_date(ev.get('Date Started'))
                e_d = parse_date(ev.get('Date Ended.1') if (is_funded_fail or is_funded_completed) else ev.get('Date Ended'))
                if s_d and e_d:
                    c_stats['total_duration_days'] += max(0, (e_d - s_d).days)
            
        # Use stored cashflow_inprogress for hedge/farming/fees (matches Net Profit In Progress display)
        # For BEF view, skip stored totals (they include all firms) — use per-eval sums instead
        # When date filtering is active, skip stored totals as they represent all-time data
        stored_cf = data.get('statistics', {}).get('cashflow_inprogress', {})
        if not is_bef and not start_date and not end_date and stored_cf and (stored_cf.get('hedging_results', 0) != 0 or stored_cf.get('farming_results', 0) != 0):
            sheet_hedge = stored_cf.get('hedging_results', 0.0) + stored_cf.get('farming_results', 0.0)
            # Compute live actual hedging from MT5 (same formula as client dashboard)
            acct = data.get('account', {})
            stats_data = data.get('statistics', {})
            hr = stats_data.get('hedging_review', {})
            try:
                mt5_dep = float(acct.get('total_deposits') or 0)
            except (ValueError, TypeError):
                mt5_dep = 0.0
            try:
                mt5_with = float(acct.get('total_withdrawals') or 0)
            except (ValueError, TypeError):
                mt5_with = 0.0
            try:
                mt5_bal = float(acct.get('balance') or 0)
            except (ValueError, TypeError):
                mt5_bal = 0.0
            hist_dep_h = 0.0; hist_with_h = 0.0; hist_bal_h = 0.0
            prior_activity = 0.0
            try:
                prior_activity = float(hr.get('current_mt5_prior_activity') or 0)
            except (ValueError, TypeError):
                pass
            for ha in (hr.get('historical_accounts') or []):
                try: hist_dep_h += float(ha.get('deposits', 0))
                except (ValueError, TypeError): pass
                try: hist_with_h += float(ha.get('withdrawals', 0))
                except (ValueError, TypeError): pass
                try: hist_bal_h += float(ha.get('final_balance', 0))
                except (ValueError, TypeError): pass
                try: prior_activity += float(ha.get('prior_activity_profit', 0))
                except (ValueError, TypeError): pass
            combined_dep = mt5_dep + hist_dep_h
            combined_with = mt5_with + hist_with_h
            combined_bal = mt5_bal + hist_bal_h
            # Only apply discrepancy if there's MT5 data
            if mt5_dep != 0 or mt5_bal != 0:
                live_actual_hedging = combined_bal - (combined_dep + combined_with) - prior_activity
                c_stats['hedge_profit'] = live_actual_hedging
            else:
                c_stats['hedge_profit'] = sheet_hedge
            c_stats['farming_profit'] = 0.0  # farming already included in hedge_profit
            c_stats['fees'] = stored_cf.get('challenge_fees', 0.0) + stored_cf.get('activation_fee', 0.0)
            # Use payouts from cashflow_inprogress so it matches Net Profit In Progress
            if stored_cf.get('payouts') is not None:
                c_stats['payouts'] = stored_cf.get('payouts', 0.0)
        else:
            # Fallback: recalculate from evaluation columns (respects date range when set)
            for ev in evaluations:
                if not isinstance(ev, dict):
                    continue
                if _is_firm_hidden(ev.get('Prop Firm')):
                    continue
                hedge_part, farming_part = _hedge_farming_for_period(ev, start_date, end_date)
                c_stats['hedge_profit'] += hedge_part
                c_stats['farming_profit'] += farming_part
            
        # 2. Deposits — use MT5 account deposits (current + historical), matching MT5 Accounts Overview
        acct = data.get('account', {})
        stats_data = data.get('statistics', {})
        hr = stats_data.get('hedging_review', {})
        # Current MT5 deposits: prefer account field, fall back to hedging_review
        try:
            current_dep = float(acct.get('total_deposits') or hr.get('total_deposits') or 0)
        except (ValueError, TypeError):
            current_dep = 0.0
        # Historical MT5 accounts deposits
        hist_dep = 0.0
        for hist_acc in (hr.get('historical_accounts') or []):
            try:
                hist_dep += float(hist_acc.get('deposits', 0))
            except (ValueError, TypeError):
                pass
        c_stats['deposits'] = abs(current_dep) + abs(hist_dep)

        # Net Profit — use stored value from cashflow_inprogress (matches Net Profit In Progress display)
        # For BEF view, always recalculate from filtered eval sums
        # When date filtering is active, always recalculate
        if not is_bef and not start_date and not end_date and stored_cf and stored_cf.get('net_profit') is not None:
            c_stats['net_profit'] = stored_cf.get('net_profit', 0.0)
        else:
            c_stats['net_profit'] = c_stats['payouts'] + c_stats['hedge_profit'] + c_stats['farming_profit'] - c_stats['fees']
        
        clients_list.append(c_stats)

    # Include hierarchy clients that have no DB records yet
    seen_clients = {c['client_id'] for c in clients_list}

    try:
        from config.hierarchy import SYSTEM_HIERARCHY
        h = SYSTEM_HIERARCHY
    except ImportError:
        h = {}

    if h and 'admins' in h:
        for admin_name, admin_data in h['admins'].items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    c_name = client.get('name')
                    if not c_name or c_name in seen_clients:
                        continue
                    c_cat = (client.get('category') or '').upper()
                    if profile_filter and profile_filter.upper() != "ALL":
                        if (c_cat or 'PRIVATE') != profile_filter.upper():
                            continue
                    clients_list.append({
                        "client_id": c_name,
                        "trader": trader_name,
                        "admin": admin_name,
                        "source": c_cat or 'PRIVATE',
                        "payouts": 0.0, "deposits": 0.0, "fees": 0.0,
                        "net_profit": 0.0, "active": 0, "passed": 0, "failed": 0,
                        "hedge_profit": 0.0, "farming_profit": 0.0
                    })
        
    return clients_list
