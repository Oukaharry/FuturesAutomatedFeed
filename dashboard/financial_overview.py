from dashboard.database import get_all_clients
import re
from datetime import datetime

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

def calculate_propfirm_overview():
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
