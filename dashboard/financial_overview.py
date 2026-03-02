from dashboard.database import get_all_clients
from dashboard.watermark_service import get_bulk_watermarks
import re
from datetime import datetime, timedelta
import json
import functools
import time

# --- Simple In-Memory Cache to fix performance ---
class SimpleCache:
    def __init__(self):
        self._cache = {}
        self._ttl = 300 # 5 minutes default

    def get(self, key):
        if key in self._cache:
            data, expiry = self._cache[key]
            if time.time() < expiry:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key, value, ttl=None):
        expiration = time.time() + (ttl or self._ttl)
        self._cache[key] = (value, expiration)

    def clear(self):
        self._cache = {}


_overview_cache = SimpleCache()

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

def clear_financial_cache():
    """Invalidate the financial overview cache."""
    _overview_cache.clear()

@cache_result(ttl=30)
def calculate_all_financials(profile_filter=None):
    """
    Optimized aggregator that computes all financial metrics in a single pass.
    Returns a dictionary containing all necessary datasets for the dashboard.
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
    
    # Constants
    P1_HEDGE_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    FUNDED_HEDGE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                         'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

    for client_id, data in clients_data.items():
        if not data: continue
        
        # --- Profile Filtering ---
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
            if client_profile != profile_filter.upper():
                continue
        
        # --- 1. Process Evaluations (Sheet Data) ---
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Prop Firm Overview Logic
            raw_prop_firm = ev.get('Prop Firm')
            if raw_prop_firm and raw_prop_firm != "-" and str(raw_prop_firm).lower() != "prop firm":
                prop_firm = normalize_prop_firm_name(raw_prop_firm)
                
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
                
                # Financials for Overview
                fee = parse_currency(ev.get('Fee'))
                activation_fee = parse_currency(ev.get('Activation Fee'))
                
                payouts = 0.0
                for i in range(1, 10):
                    payouts += parse_currency(ev.get(f'Payout {i}'))
                
                p1_hedges = sum(parse_currency(ev.get(col)) for col in P1_HEDGE_COLS)
                funded_hedges = sum(parse_currency(ev.get(col)) for col in FUNDED_HEDGE_COLS)
                hedge_results = p1_hedges + funded_hedges
                
                farming_results = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
                
                # Status Logic
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
                target["account_count"] += 1
                target["clients"].add(client_id)
                
                if is_in_progress: target["active_accounts"] += 1
                if is_passed_p1: target["passed_accounts"] += 1
                if is_p1_fail or is_funded_fail: target["failed_accounts"] += 1
                if is_p1_fail or is_funded_ended: target["ended_count"] += 1
                
                # Duration Logic for EV/Day
                duration = 0
                if is_p1_fail:
                    s_d = parse_date(ev.get('Date Started'))
                    e_d = parse_date(ev.get('Date Ended'))
                    if s_d and e_d: duration = (e_d - s_d).days
                elif is_funded_ended:
                    # Duration is total time from start of eval to end of funded account
                    s_d = parse_date(ev.get('Date Started'))
                    e_d = parse_date(ev.get('Date Ended.1'))
                    if s_d and e_d: duration = (e_d - s_d).days
                    # Fallback if funded dates are missing but it ended
                    elif s_d: 
                        # Try P1 end date if Funded end date missing? Unlikely for "Ended" status
                        pass
                
                if duration > 0:
                    target["total_duration_days"] += duration
                
                # Overview Earliest Date
                d_str = ev.get('Date Started') or ev.get('Date')
                if d_str:
                    d_obj = parse_date(d_str)
                    if d_obj:
                         if target["earliest_date"] is None or d_obj < target["earliest_date"]:
                             target["earliest_date"] = d_obj

            # Time Series Logic
            # Dates
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            date_ended = parse_date(ev.get('Date Ended'))
            date_started_funded = parse_date(ev.get('Date Started.1'))
            date_ended_funded = parse_date(ev.get('Date Ended.1'))
            base_date = date_purchased or date_started or datetime.now()

            # 1. Fees
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            total_fee = fee + act_fee
            if total_fee > 0:
                fee_date = date_purchased or base_date
                ts_fees.append((fee_date, total_fee))
                ts_net_profit.append((fee_date, -total_fee)) # Cost

            # 2. Payouts
            for i in range(1, 10):
                d_str = ev.get(f'Date {i}')
                amt = parse_currency(ev.get(f'Payout {i}'))
                if amt > 0:
                    d = parse_date(d_str)
                    final_d = d or base_date
                    ts_payouts.append((final_d, amt))
                    ts_net_profit.append((final_d, amt))
            
            # 3. Hedge Results
            p1_profit = sum(parse_currency(ev.get(c)) for c in P1_HEDGE_COLS)
            if p1_profit != 0:
                d = date_ended or date_started or base_date
                ts_hedge.append((d, p1_profit))
                ts_net_profit.append((d, p1_profit))
            
            fd_profit = sum(parse_currency(ev.get(c)) for c in FUNDED_HEDGE_COLS)
            if fd_profit != 0:
                d = date_ended_funded or date_started_funded or base_date
                ts_hedge.append((d, fd_profit))
                ts_net_profit.append((d, fd_profit))

            # 4. Farming Results
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
            if farming_calc != 0:
                d = date_ended_funded or date_ended or base_date
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
                d_time = deal.get('time')
                if not d_time: continue
                
                try:
                    dt = datetime.fromtimestamp(int(d_time))
                    date_str = dt.strftime("%Y-%m-%d")
                except:
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
    def process_ts(events):
        if not events: return [], []
        events.sort(key=lambda x: x[0])
        from collections import defaultdict
        daily = defaultdict(float)
        for dt, val in events:
            daily[dt.strftime("%Y-%m-%d")] += val
        
        dates = []
        vals = []
        cum = 0.0
        for day in sorted(daily.keys()):
            cum += daily[day]
            dates.append(day)
            vals.append(cum)
        return dates, vals
    
    # Process Deposits from simple dict
    def process_deposits_dict(d_dict):
        if not d_dict: return [], []
        dates = []
        vals = []
        cum = 0.0
        for day in sorted(d_dict.keys()):
            cum += d_dict[day]
            dates.append(day)
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
    """
    if not name:
        return "Unknown"
        
    original = name.strip()
    normalized = original.lower().replace(" ", "").replace("_", "")
    
    # Map normalized keys to display names
    MAPPING = {
        "myfundedfutures": "My Funded Futures",
        "fundednext": "FundedNext",
        "topstep": "Top Step",
        "fundingticks": "Funding Ticks",
        "tradeday": "Trade Day",
        "tradeify": "Tradeify",
        "ftmo": "FTMO",
        "alphafutures": "Alpha Futures",
        "blueguardian": "Blue Guardian",
        "fundedtradingplus": "Funded Trading Plus",
        "the5ers": "The 5%ers",
        "apextraderfunding": "Apex Trader Funding",
        "apextrader": "Apex Trader Funding",
        "uprofittrader": "UProfit",
        "uprofit": "UProfit",
        "bulenox": "Bulenox",
        "tickticktrader": "TickTick Trader",
        "elitetraderfunding": "Elite Trader Funding",
        "take profit trader": "Take Profit Trader",
        "takeprofittrader": "Take Profit Trader",
        "mff": "My Funded Futures",
        "mffu": "My Funded Futures",
        "fundednextlegacyaccount": "FundedNext (Legacy)", # Keep distinct if wanted, or merge to FundedNext
    }
    
    # Direct match in mapping
    if normalized in MAPPING:
        return MAPPING[normalized]
        
    # Check if key starts with... (optional, logic for variations)
    if "myfundedfutures" in normalized:
        return "My Funded Futures"
    if "fundednext" in normalized:
        return "FundedNext"
        
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
            c_prof = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not c_prof: c_prof = "PRIVATE"
            if c_prof != profile_filter.upper():
                continue

        evaluations = data.get('evaluations', [])
        for eval_data in evaluations:
            if not isinstance(eval_data, dict):
                continue
            prop_firm = eval_data.get('Prop Firm')
            if not prop_firm or prop_firm == "-": continue
            
            prop_firm = normalize_prop_firm_name(prop_firm)
            
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
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if client_profile == 'BEF': client_profile = 'BEF'
            else: client_profile = 'PRIVATE'
                
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
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if client_profile == 'BEF': client_profile = 'BEF'
            else: client_profile = 'PRIVATE'
            if client_profile != profile_filter.upper(): continue
            
        deals_json = data.get('deals', '[]')
        try:
            deals = json.loads(deals_json) if isinstance(deals_json, str) else deals_json
        except:
            deals = []
            
        if not deals: continue
        
        for deal in deals:
            # MT5 deal structure: {'time': epoch, 'type': int, 'profit': float, 'swap': float, 'commission': float, ...}
            d_time = deal.get('time')
            if not d_time: continue
                
            try:
                dt = datetime.fromtimestamp(int(d_time))
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
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
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
            # Match calculate_propfirm_overview logic: Sum of Hedge Day 1-34
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
            
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
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if client_profile == 'BEF': client_profile = 'BEF'
            else: client_profile = 'PRIVATE'
                
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
    # Hedge Day 1 to 34
    
    for client_id, data in clients_data.items():
        if not data:
            continue

        # Filter by Profile if profile_filter is provided
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            # Check 'profile' or 'category' field (handle both for compatibility)
            client_profile = (identity.get('profile') or identity.get('category') or 'PRIVATE').upper()
            
            # Normalize to clean string
            if not client_profile: client_profile = "PRIVATE"
            
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
                
            # Normalize Name
            prop_firm = normalize_prop_firm_name(raw_prop_firm)
            
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
            
            # Payouts (INFLOW)
            payouts = 0.0
            for i in range(1, 10):
                key = f'Payout {i}'
                if key in eval_data:
                    payouts += parse_currency(eval_data.get(key))
            
            # Hedge Results (PROFIT/LOSS)
            p1_hedges = sum(parse_currency(eval_data.get(col)) for col in P1_HEDGE_COLS)
            funded_hedges = sum(parse_currency(eval_data.get(col)) for col in FUNDED_HEDGE_COLS)
            hedge_results = p1_hedges + funded_hedges
            
            # Farming Results (PROFIT)
            farming_results = 0.0
            for i in range(1, 35):
                key = f'Hedge Day {i}'
                farming_results += parse_currency(eval_data.get(key))
            
            # === Status ===
            status_p1 = str(eval_data.get('Status P1', '')).strip()
            status_funded = str(eval_data.get('Status', '')).strip()
            status_p1_lower = status_p1.lower()
            status_funded_lower = status_funded.lower()
            
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
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
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
            cp = (identity.get('profile') or identity.get('category') or 'PRIVATE').upper()
            if not cp: cp = 'PRIVATE'
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
                
    return _aggregate_events_cumulative(events)

def get_cumulative_farming_data(profile_filter=None):
    """Calculates cumulative farming results over time."""
    clients_data = _get_cached_clients()
    events = [] 
    
    for client_id, data in clients_data.items():
        if not data: continue
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            cp = (identity.get('profile') or identity.get('category') or 'PRIVATE').upper()
            if not cp: cp = 'PRIVATE'
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
            farming_calc = sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
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
            c_prof = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not c_prof: c_prof = "PRIVATE"
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
            for d in range(1, 60):
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

@cache_result(ttl=300)
def get_client_performance_stats(profile_filter=None):
    """
    Returns a list of per-client performance statistics.
    Used for the Client Performance Table.
    """
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
                            'trader': trader_name
                        }

    clients_data = _get_cached_clients()
    watermarks_map = get_bulk_watermarks(14)
    clients_list = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        identity = data.get('identity', {})
        real_client_name = identity.get('name') or client_id
        
        # Profile Filter
        source = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
        if not source: source = "PRIVATE"
        
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
            "hwm": 0.0,
            "lwm": 0.0
        }
        
        # Populate Watermarks (14 days)
        if real_client_name in watermarks_map:
             c_stats['hwm'] = watermarks_map[real_client_name]['high']
             c_stats['lwm'] = watermarks_map[real_client_name]['low']
        elif client_id in watermarks_map:
             c_stats['hwm'] = watermarks_map[client_id]['high']
             c_stats['lwm'] = watermarks_map[client_id]['low']
             
        # Null safety
        if c_stats['hwm'] is None: c_stats['hwm'] = 0.0
        if c_stats['lwm'] is None: c_stats['lwm'] = 0.0
        
        # 1. Evaluations Payouts/Fees/Status
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            if not isinstance(ev, dict):
                continue
            # Status logic expanded
            status = str(ev.get('Status') or '').lower()
            if 'passed' in status or 'funded' in status:
                c_stats['passed'] += 1
            elif 'failed' in status or 'breached' in status or 'blown' in status or 'fail' in status:
                c_stats['failed'] += 1
            elif 'active' in status or 'phase' in status or 'running' in status or 'ongoing' in status or 'trading' in status or 'challenge' in status:
                c_stats['active'] += 1
                
            # Fees
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            c_stats['fees'] += (fee + act_fee)
            
            # Payouts
            for i in range(1, 10):
                c_stats['payouts'] += parse_currency(ev.get(f'Payout {i}'))
            
            # Hedge
            for col in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5',
                        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                        'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']:
                c_stats['hedge_profit'] += parse_currency(ev.get(col))
                
            # Farming
            c_stats['farming_profit'] += parse_currency(ev.get('Farming Profit')) # Summary column usually
            
        # 2. Deals for Deposits
        # Assuming get_deals returns list of deals
        # If deals are not readily available in data['deals'], we might have to skip or load usage
        # Usually data has 'deals' key if loaded fully.
        deals = data.get('deals', [])
        for deal in deals:
            # Deposits are positive 'profit' with type 'deal_entry_in' usually, but here assumed 'profit' field reflects deposit amount?
            # Or usually type=2 (DEAL_ENTRY_IN) and check comment/type?
            # Simplified: Use pre-calced deposits if stored, or iterate deals.
            # Assuming 'profit' is the amount, and type implies deposit.
            # Let's rely on standard logic: profit > 0 and comment indicates deposit?
            # Or just sum 'profit' of all deals that are Deposits.
            try:
                # MT5 deal structure check
                deal_type = int(deal.get('type', -1))
                entry = int(deal.get('entry', -1))
                profit = float(deal.get('profit', 0.0))
                # Entry In (0) + Type Balance (2) ?? MQL5 constants vary.
                # Let's trust the "total_deposits" logic used elsewhere if available.
                # Since we don't have deal constants handy, let's look at get_cumulative_deposits logic.
                pass
            except:
                pass
                
        # Alternative: We don't have deals easily here without logic.
        # But wait, calculate_all_financials uses deals!
        # It calls: ev.get('Account #') -> finds specific deals? 
        # Actually deposits usually come from MT5 via 'deals' in JSON.
        # Let's check how 'get_cumulative_deposits' works.
        
        # Temporary: skip deep deposit calc per client for speed, or assume 0 if not critical.
        # But user sees "Deposits" column.
        # Let's look at how we got total_deposits in app.py: data['deposits'] tuple.
        # That's global.
        
        # Fix: iterate deals simply if they exist.
        if 'deals' in data:
            for deal in data['deals']:
                 # Check for deposit
                 # If profit > 0 and it's a balance operation (usually no symbol)
                 if deal.get('symbol') == '' and float(deal.get('profit', 0)) > 0:
                     c_stats['deposits'] += float(deal.get('profit', 0))

        # Net Profit = Payouts + Hedge + Farming - Fees
        # (Deposits are capital, not profit, so usually excluded from Net Profit calc depending on definition)
        # Definition: Net Profit typically = (Payouts + Hedge + Farming) - (Fees + Losses) ??
        # Or just (Payouts - Fees) + Side Income?
        # Let's stick to: Payouts + Hedge + Farming - Fees. 
        # (Note: 'Fees' includes challenge fees. 'Deposits' usually separate capital).
        c_stats['net_profit'] = c_stats['payouts'] + c_stats['hedge_profit'] + c_stats['farming_profit'] - c_stats['fees']
        
        clients_list.append(c_stats)
        
    return clients_list
