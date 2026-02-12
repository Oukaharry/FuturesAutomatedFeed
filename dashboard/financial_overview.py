from dashboard.database import get_all_clients
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

@cache_result(ttl=300)
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
        "ev_per_day": 0.0
    }

    for firm in overview:
        data = overview[firm]
        data["net"] = data["total_payouts"] + data["hedge_results"] + data["farming_results"] - (data["total_fees"] + data["total_activation_fees"])
        
        # Accumulate global
        global_stats["net"] += data["net"]
        global_stats["ended"] += data["ended_count"]
        
        if data.get("earliest_date"):
            if global_stats["earliest"] is None or data["earliest_date"] < global_stats["earliest"]:
                global_stats["earliest"] = data["earliest_date"]
        
        ended = data.get("ended_count", 0)
        data["expected_value"] = data["net"] / ended if ended > 0 else 0.0
        
        data["ev_per_day"] = 0.0
        if data.get("earliest_date"):
            days = (datetime.now() - data["earliest_date"]).days
            if days > 0:
                data["ev_per_day"] = data["net"] / days
        
        if "earliest_date" in data: del data["earliest_date"]
        data["total_clients"] = len(data["clients"])
        del data["clients"]
        
    # Finalize Global Stats
    if global_stats["ended"] > 0:
        global_stats["expected_value"] = global_stats["net"] / global_stats["ended"]
        
    if global_stats["earliest"]:
        days = (datetime.now() - global_stats["earliest"]).days
        if days > 0:
            global_stats["ev_per_day"] = global_stats["net"] / days
    # Remove datetime object before return
    if "earliest" in global_stats: del global_stats["earliest"]

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

def get_payouts_history(start_date=None, end_date=None, prop_firm_filter=None):
    """
    Returns a list of all payouts with details.
    """
    clients_data = _get_cached_clients()
    payouts_list = []
    
    for client_id, data in clients_data.items():
        if not data:
            continue
            
        evaluations = data.get('evaluations', [])
        for eval_data in evaluations:
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
                # Note: Screenshot or structure might have explicit date columns or shared?
                # Usually Payout 1 corresponds to a date column if it exists. 
                # Let's assume standard "Date 1", "Date 2" etc based on earlier file reads or infer from known structure.
                # data_processor.py listed: 'Payout 1', 'Date 1', 'Payout 2', 'Date 2'...
                
                amount = parse_currency(eval_data.get(p_key))
                if amount > 0:
                    date_str = eval_data.get(d_key)
                    date_obj = parse_date(date_str)
                    
                    # Store if date exists (or include even if no date?)
                    # If we filter by date, we need a date.
                    
                    if date_obj:
                        # Filter check
                        if start_date and date_obj < start_date:
                            continue
                        if end_date and date_obj > end_date:
                            continue
                            
                        payouts_list.append({
                            "date": date_obj,
                            "date_str": date_str, # Keep original string for display
                            "prop_firm": prop_firm,
                            "amount": amount,
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

def calculate_trader_stats():
    """Calculates aggregated statistics per trader."""
    clients_data = _get_cached_clients()
    traders_stats = {}
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        identity = data.get('identity', {})
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
        for ev in evaluations:
            acc_num = ev.get('Account #') or ev.get('Account #.1') or 'Unknown'
            # Payouts 1-10
            for i in range(1, 11):
                val = ev.get(f'Payout {i}')
                amt = parse_currency(val) if val else 0.0
                if amt > 0: stats['total_payouts'] += amt
            
            # Negative Hedge Logic
            hedge_sum = 0.0
            has_activity = False
            
            check_list = []
            for i in range(1, 6):
                check_list.append(f'Hedge Result {i}')
                check_list.append(f'Hedge Result {i}.1')
                check_list.append(f'Hedge Result {i}.2')
            
            for k in check_list:
                val = parse_currency(ev.get(k))
                if val != 0:
                    has_activity = True
                    hedge_sum += val
            
            if has_activity and hedge_sum < -1.0: 
                stats['total_negative_hedge'] += hedge_sum
                stats['negative_hedge_details'].append({
                    "client": client_id,
                    "account": acc_num,
                    "amount": hedge_sum,
                    "link": f"/dashboard/{client_id}"
                })
            
            # Farming Logic
            for d in range(1, 60):
                h_val = parse_currency(ev.get(f'Hedge Day {d}'))
                if h_val != 0:
                    stats['farming_days_count'] += 1
                    
                    p_val_raw = ev.get(f'Day {d} Profit')
                    if not p_val_raw or str(p_val_raw).strip() in ['', '-']:
                        stats['farming_missing_notes'] += 1
                        stats['farming_warnings'].append({
                            "client": client_id,
                            "day": d,
                            "link": f"/dashboard/{client_id}"
                        })

    return list(traders_stats.values())
