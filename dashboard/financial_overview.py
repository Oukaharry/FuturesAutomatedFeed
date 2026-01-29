from dashboard.database import get_all_clients
import re

def parse_currency(value_str):
    """
    Parses a currency string like "$120.65", "1,200.00", "-", "$ -" into a float.
    Returns 0.0 if the value is missing or represents zero.
    """
    if not value_str or not isinstance(value_str, str):
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

def calculate_propfirm_overview():
    """
    Aggregates financial data by Prop Firm.
    Returns a dictionary:
    {
        "Prop Firm Name": {
            "total_fees": float,
            "total_activation_fees": float,
            "total_payouts": float,
            "net": float,
            "account_count": int
        },
        ...
    }
    """
    clients_data = get_all_clients() # Returns {client_id: full_data_dict}
    
    overview = {}
    
    for client_id, data in clients_data.items():
        if not data:
            continue
            
        evaluations = data.get('evaluations', [])
        if not evaluations:
            continue
            
        for eval_data in evaluations:
            prop_firm = eval_data.get('Prop Firm')
            
            # Skip if no prop firm name or if it's header/invalid
            if not prop_firm or prop_firm == "-" or prop_firm.lower() == "prop firm":
                continue
                
            prop_firm = prop_firm.strip()
            
            if prop_firm not in overview:
                overview[prop_firm] = {
                    "total_fees": 0.0,
                    "total_activation_fees": 0.0,
                    "total_payouts": 0.0,
                    "net": 0.0,
                    "account_count": 0
                }
            
            # Fees
            fee = parse_currency(eval_data.get('Fee'))
            activation_fee = parse_currency(eval_data.get('Activation Fee'))
            
            # Payouts (Payout 1, Payout 2, Payout 3, Payout 4)
            payouts = 0.0
            for i in range(1, 10): # Check Payout 1 to 9 just in case
                key = f'Payout {i}'
                if key in eval_data:
                    payouts += parse_currency(eval_data.get(key))
            
            # Update totals
            overview[prop_firm]["total_fees"] += fee
            overview[prop_firm]["total_activation_fees"] += activation_fee
            overview[prop_firm]["total_payouts"] += payouts
            overview[prop_firm]["account_count"] += 1
            
    # Calculate Net
    for firm in overview:
        data = overview[firm]
        # Net = Payouts - Fees - Activation Fees
        data["net"] = data["total_payouts"] - (data["total_fees"] + data["total_activation_fees"])
        
    return overview
