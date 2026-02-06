from dashboard.database import get_all_clients
import re
from datetime import datetime
import json
try:
    from config.settings import SHEET_URL
except ImportError:
    # Fallback or development url
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1vtuGcTe8ys44wHCJGJr6VoImeh8q0beaKkZMt0hd3VU/edit?usp=sharing"

def get_col_letter(n):
    """Convert 1-based column number to letter (e.g. 1->A, 27->AA)"""
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string

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
    clients_data = get_all_clients()
    payouts_list = []
    
    for client_id, data in clients_data.items():
        if not data:
            continue
            
        # Determine Client Name
        identity = data.get('identity', {})
        client_name = client_id
        if identity:
            first = identity.get('First Name', '').strip()
            last = identity.get('Last Name', '').strip()
            full = identity.get('Name', '').strip()
            
            if first and last:
                client_name = f"{first} {last}"
            elif first:
                client_name = first
            elif full:
                client_name = full
        
        trader_name = identity.get('trader', '-')
        admin_name = identity.get('admin', '-')

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
                            "client_name": client_name,
                            "trader_name": trader_name,
                            "admin_name": admin_name,
                            "account": account_num,
                            "account_id": account_num
                        })
    
    # Sort by date desc
    payouts_list.sort(key=lambda x: x['date'], reverse=True)
    return payouts_list

def get_propfirm_breakdown(metric, profile_filter=None):
    """
    Calculates cumulative growth categorized by Prop Firm.
    metric: 'payouts' or 'fees'
    Returns: { 
        'All': {'dates': [], 'values': []}, 
        'FirmA': {'dates': [], 'values': []},
        ...
    }
    """
    clients_data = get_all_clients()
    
    from collections import defaultdict
    # Structure: firm_name -> {date_str: daily_amount}
    firm_daily_changes = defaultdict(lambda: defaultdict(float))
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            # Check for valid prop firm
            raw_prop_firm = ev.get('Prop Firm')
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue
            
            prop_firm = normalize_prop_firm_name(raw_prop_firm)
            
            # Date Fallback
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            base_date = date_purchased or date_started or datetime.now()
            
            if metric == 'payouts':
                for i in range(1, 10):
                    d_str = ev.get(f'Date {i}')
                    amount = parse_currency(ev.get(f'Payout {i}'))
                    if amount > 0:
                        d = parse_date(d_str) or base_date
                        d_str_fmt = d.strftime("%Y-%m-%d")
                        firm_daily_changes[prop_firm][d_str_fmt] += amount
                        firm_daily_changes['All'][d_str_fmt] += amount
                        
            elif metric == 'fees':
                fee = parse_currency(ev.get('Fee'))
                act_fee = parse_currency(ev.get('Activation Fee'))
                total_fee = fee + act_fee
                if total_fee > 0:
                    d_str_fmt = base_date.strftime("%Y-%m-%d")
                    firm_daily_changes[prop_firm][d_str_fmt] += total_fee
                    firm_daily_changes['All'][d_str_fmt] += total_fee

    # Process into cumulative arrays
    result = {}
    
    # Ensure 'All' exists even if empty
    if 'All' not in firm_daily_changes:
        result['All'] = {'dates': [], 'values': []}
        
    for firm, daily_map in firm_daily_changes.items():
        sorted_days = sorted(daily_map.keys())
        dates = []
        values = []
        cumulative = 0.0
        
        for day in sorted_days:
             cumulative += daily_map[day]
             dates.append(day)
             values.append(cumulative)
             
        result[firm] = {'dates': dates, 'values': values}
        
    return result

def get_payouts_growth_data(profile_filter=None):
    """
    Calculates cumulative payouts over time (ignoring fees).
    Returns lists of labels (dates) and data points (cumulative payouts).
    """
    clients_data = get_all_clients()
    events = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            # Check for valid prop firm
            raw_prop_firm = ev.get('Prop Firm')
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue
                
            # Date Fallback
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            base_date = date_purchased or date_started or datetime.now()
            
            # Payouts Only
            for i in range(1, 10):
                d_str = ev.get(f'Date {i}')
                amount = parse_currency(ev.get(f'Payout {i}'))
                if amount > 0:
                    d = parse_date(d_str)
                    events.append((d or base_date, amount))
    
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

def get_cumulative_fees(profile_filter=None):
    """
    Calculates cumulative fees (Fee + Activation Fee) over time.
    Returns lists of labels (dates) and data points (cumulative fees).
    """
    clients_data = get_all_clients()
    events = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            # Check for valid prop firm
            raw_prop_firm = ev.get('Prop Firm')
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue
                
            # Date Fallback
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            base_date = date_purchased or datetime.now()
            
            # Fees (Positive value for graph usually, or negative? 
            # Summary card shows positive value "Total Fees $X". 
            # Graph should probably show cumulative positive cost or negative flow?
            # "Total Payouts" is positive. "Total Fees" as a positive cost accumulation makes sense to compare magnitude.
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            total_fee = fee + act_fee
            
            if total_fee > 0:
                events.append((base_date, total_fee))
    
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
    clients_data = get_all_clients()
    
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

def get_cumulative_trading_profit(profile_filter=None):
    """
    Calculates cumulative Net Profit over time based on Payouts, Hedge Results, Farming, and Fees.
    Uses Evaluation data (Sheet) to match the Summary Card 'Net Profit'.
    """
    clients_data = get_all_clients()
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

def get_portfolio_growth_data(profile_filter=None):
    """
    Calculates cumulative portfolio growth (Payouts - Fees) over time.
    Returns lists of labels (dates) and data points (net cashflow).
    Note: Matches 'Net Profit (Trading)' graph logic generally but excludes internal hedge/farming profit.
    """
    clients_data = get_all_clients()
    events = []
    
    for client_id, data in clients_data.items():
        if not data: continue
        
        # Apply Profile Filter
        if profile_filter and profile_filter.upper() != "ALL":
            identity = data.get('identity', {})
            client_profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
            if not client_profile: client_profile = "PRIVATE"
            if client_profile != profile_filter.upper():
                continue
        
        evaluations = data.get('evaluations', [])
        for ev in evaluations:
            # Check for valid prop firm
            raw_prop_firm = ev.get('Prop Firm')
            if not raw_prop_firm or raw_prop_firm == "-" or str(raw_prop_firm).lower() == "prop firm":
                continue
            
            # Extract Dates for Fallbacks
            date_purchased = parse_date(ev.get('Date Purchased') or ev.get('Date'))
            date_started = parse_date(ev.get('Date Started'))
            base_date = date_purchased or date_started or datetime.now()
            
            # 1. Payouts (Positive)
            for i in range(1, 10):
                d_str = ev.get(f'Date {i}')
                amount = parse_currency(ev.get(f'Payout {i}'))
                if amount > 0:
                    d = parse_date(d_str)
                    events.append((d or base_date, amount))
            
            # 2. Fees (Negative)
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            total_fee = fee + act_fee
            if total_fee > 0:
                events.append((date_purchased or base_date, -total_fee))
                
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

def calculate_propfirm_overview(profile_filter=None):
    """
    Aggregates financial data by Prop Firm.
    Returns a dictionary.
    """
    clients_data = get_all_clients() # Returns {client_id: full_data_dict}
    
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
        
        # Convert set to count
        data["total_clients"] = len(data["clients"])
        del data["clients"]
        
    return overview

def get_trader_performance_data():
    """
    Aggregates performance metrics by Trader.
    metrics:
    - Total Payouts
    - Total Negative Hedge Net (only if actual hedging results exist)
    - Farming check: count of farming days where Note/Prop Day is missing?
      (For now, we'll track 'Farming Days' and 'Missing Prop Day Info' if logic applies)
    """
    clients_data = get_all_clients()
    traders = {} # name -> data

    for client_id, data in clients_data.items():
        if not data: continue
        
        identity = data.get('identity', {})
        trader_name = identity.get('trader', 'Unassigned')
        if not trader_name or trader_name == '-' or str(trader_name).lower() == 'nan': 
            trader_name = 'Unassigned'
        
        if trader_name not in traders:
            traders[trader_name] = {
                "name": trader_name,
                "total_payouts": 0.0,
                "total_negative_hedge": 0.0,
                "farming_days_count": 0,
                "farming_missing_notes": 0,
                "client_count": 0,
                "sheets_reviewed": 0,
                "negative_hedge_details": [], # List of {client, account, amount}
                "farming_warnings": []        # List of {client, account, day, msg}
            }
            
        t_data = traders[trader_name]
        t_data["client_count"] += 1
        
        evaluations = data.get('evaluations', [])
        t_data["sheets_reviewed"] += len(evaluations)
        
        for idx, ev in enumerate(evaluations):
            # Calculate Excel Row Number (Assuming data starts at Row 3)
            row_num = idx + 3
            
            # 1. Payouts
            for i in range(1, 10):
                amt = parse_currency(ev.get(f'Payout {i}'))
                if amt > 0:
                    t_data["total_payouts"] += amt
            
            # 2. Negative Hedge Nets (Conditional per phase)
            # Only count negative hedge nets if there are ACTUAL POSITIVE hedging results for that specific phase.
            
            # Phase 1 Check
            p1_hedge_sum = sum(parse_currency(ev.get(k)) for k in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5'])
            
            if p1_hedge_sum != 0:
                hn1 = parse_currency(ev.get('Hedge Net'))
                if hn1 < -1: # Use -1 to ignore tiny rounding floats
                    t_data["total_negative_hedge"] += hn1
                    t_data["negative_hedge_details"].append({
                        "client": identity.get('Name') or client_id,
                        "account": f"{ev.get('Account #') or 'P1'} (Phase 1)",
                        "amount": hn1,
                        "link": f"/dashboard/{client_id}?range=N{row_num}"
                    })

            # Funded Phase Check
            funded_hedge_sum = sum(parse_currency(ev.get(k)) for k in ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
                      'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7'])
            
            if funded_hedge_sum != 0:
                hn2 = parse_currency(ev.get('Hedge Net.1'))
                if hn2 < -1:
                    t_data["total_negative_hedge"] += hn2
                    t_data["negative_hedge_details"].append({
                        "client": identity.get('Name') or client_id,
                        "account": f"{ev.get('Account #.1') or 'Funded'} (Funded)",
                        "amount": hn2,
                        "link": f"/dashboard/{client_id}?range=AA{row_num}"
                    })

            # 3. Farming - Check for missing notes (Prop Day empty when Hedge Day has value)
            for d in range(1, 35):
                hd_val = parse_currency(ev.get(f'Hedge Day {d}'))
                pd_val = ev.get(f'Prop Day {d}') 
                
                # If we have a hedge result for the day
                if hd_val != 0:
                    t_data["farming_days_count"] += 1
                    
                    # Check if 'Prop Day' (Note/Date) is empty
                    # Prop Day is often used for the result in the prop firm or date/note
                    is_missing = False
                    if pd_val is None:
                        is_missing = True
                    elif isinstance(pd_val, str) and not pd_val.strip():
                        is_missing = True
                    elif isinstance(pd_val, (int, float)) and pd_val == 0:
                         # Warning: 0 might be a valid result, but usually Prop Day matches Hedge Day if it's a value
                         # If it's a note, 0 is weird.
                         # Let's assume emptiness or "0" means missing if Hedge Day is non-zero
                         pass 
                         
                    # For now, strict empty check for strings, None for others
                    if str(pd_val).strip() in ['', '-', 'nan', 'None']:
                        
                        col_letter = get_col_letter(37 + (d-1)*2) # AK=37 (Prop Day 1)
                        t_data["farming_missing_notes"] += 1
                        t_data["farming_warnings"].append({
                            "client": identity.get('Name') or client_id,
                            "account": ev.get('Account #') or ev.get('Account #.1'),
                            "day": d,
                            "link": f"/dashboard/{client_id}?range={col_letter}{row_num}"
                        })

    return sorted(list(traders.values()), key=lambda x: x['total_payouts'], reverse=True)
