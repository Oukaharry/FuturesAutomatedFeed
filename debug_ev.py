"""Debug EV calculation"""
import sys
sys.path.insert(0, '.')
from config.settings import SHEET_URL
from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency

# Get the data (returns a list of evaluations as dicts)
evaluations = fetch_evaluations(SHEET_URL)
print(f"Fetched {len(evaluations)} evaluations")
if evaluations:
    # Check what first evaluation looks like
    print(f"First eval keys: {list(evaluations[0].keys())[:10]}...")
    
    # Calculate statistics
    stats = calculate_statistics(evaluations, None, None)
    
    print("=== EV Calculation Debug ===")
    print(f"Funded Rate: {stats['eval_totals'].get('funded_rate', 0):.2f}%")
    print(f"Avg Net Failed (Eval): ${stats['eval_totals'].get('avg_net_failed', 0):.2f}")
    print(f"Avg Net Completed (Funded): ${stats['funded_totals'].get('avg_net_completed', 0):.2f}")
    print(f"Calculated EV: ${stats.get('expected_value', 0):.2f}")
    
    print("\n=== Failed Eval Net Profit Details ===")
    # Status P1 = 'Fail' for failed evals 
    failed_evals = [e for e in evaluations if str(e.get('Status P1','')).lower() == 'fail']
    print(f"Total failed P1 evals: {len(failed_evals)}")
    
    total_net = 0
    count = 0
    for ev in failed_evals:
        fee = parse_currency(ev.get('Fee', 0))
        payout = parse_currency(ev.get('Payout', 0))
        p1_hedges = parse_currency(ev.get('Hedge Net', 0))
        funded_hedges = parse_currency(ev.get('Hedge Net.1', 0))
        farming_net = parse_currency(ev.get('Farming Net', 0))
        hedge_days = parse_currency(ev.get('Hedge Days', 0))
        
        total_hedge = p1_hedges + funded_hedges
        total_farm = farming_net + hedge_days
        net_profit = payout + total_hedge + total_farm - fee
        total_net += net_profit
        count += 1
        
        if count <= 5:
            print(f"  Fee: ${fee:.2f}, Payout: ${payout:.2f}, Hedge: ${total_hedge:.2f}, Farm: ${total_farm:.2f} -> Net: ${net_profit:.2f}")
    
    print(f"\nTotal net for {count} failed evals: ${total_net:.2f}")
    print(f"Average: ${total_net/count if count > 0 else 0:.2f}")
    
    print("\n=== Completed Funded Net Profit Details ===")
    # Status (funded) = 'Completed' 
    completed_funded = [e for e in evaluations if str(e.get('Status','')).lower() == 'completed']
    print(f"Total completed funded: {len(completed_funded)}")
    
    total_completed_net = 0
    comp_count = 0
    for ev in completed_funded:
        fee = parse_currency(ev.get('Fee', 0))
        payout = parse_currency(ev.get('Payout', 0))
        p1_hedges = parse_currency(ev.get('Hedge Net', 0))
        funded_hedges = parse_currency(ev.get('Hedge Net.1', 0))
        farming_net = parse_currency(ev.get('Farming Net', 0))
        hedge_days = parse_currency(ev.get('Hedge Days', 0))
        
        total_hedge = p1_hedges + funded_hedges
        total_farm = farming_net + hedge_days
        net_profit = payout + total_hedge + total_farm - fee
        total_completed_net += net_profit
        comp_count += 1
        
        if comp_count <= 5:
            print(f"  Fee: ${fee:.2f}, Payout: ${payout:.2f}, Hedge: ${total_hedge:.2f}, Farm: ${total_farm:.2f} -> Net: ${net_profit:.2f}")
    
    print(f"\nTotal net for {comp_count} completed: ${total_completed_net:.2f}")
    print(f"Average: ${total_completed_net/comp_count if comp_count > 0 else 0:.2f}")
else:
    print("Failed to fetch data")
