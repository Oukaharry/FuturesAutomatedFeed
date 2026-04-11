"""Focused: Just show Chris hedging totals and diffs."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data
from utils.data_processor import calculate_statistics

def pc(val):
    if val is None or val == '' or val == '-': return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace('$','').replace(',','').replace(' ','')
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    try: return float(s)
    except: return 0.0

data = get_client_data('Chris')
evaluations = data.get('evaluations', [])
print(f"Evaluations: {len(evaluations)}")

# Run calculate_statistics
stats = calculate_statistics(evaluations, None, None)
cf = stats['cashflow_inprogress']
pcf = stats['profitability_completed']

print(f"\n=== Dashboard (calculate_statistics) ===")
print(f"In-progress: fees={cf['challenge_fees']:.2f} hedging={cf['hedging_results']:.2f} farming={cf['farming_results']:.2f} payouts={cf['payouts']:.2f}")
print(f"Completed:   fees={pcf['challenge_fees']:.2f} hedging={pcf['hedging_results']:.2f} farming={pcf['farming_results']:.2f} payouts={pcf['payouts']:.2f}")

print(f"\n=== Sheet values ===")
print(f"In-progress: fees=58460.49 hedging=-16555.37 farming=9463.34 payouts=125768.58")
print(f"Completed:   fees=56199.34 hedging=-1726.42 farming=6330.84 payouts=115465.98")

print(f"\n=== Diffs (DB - Sheet) ===")
print(f"IP Hedging: {cf['hedging_results'] - (-16555.37):.2f}")
print(f"CP Hedging: {pcf['hedging_results'] - (-1726.42):.2f}")
print(f"IP Farming: {cf['farming_results'] - 9463.34:.2f}")
print(f"CP Farming: {pcf['farming_results'] - 6330.84:.2f}")
print(f"IP Payouts: {cf['payouts'] - 125768.58:.2f}")
print(f"CP Payouts: {pcf['payouts'] - 115465.98:.2f}")
print(f"IP Fees:    {cf['challenge_fees'] - 58460.49:.2f}")
print(f"CP Fees:    {pcf['challenge_fees'] - 56199.34:.2f}")

# Check if stats_tab override exists in stored data
stored_stats = data.get('statistics', {})
print(f"\n=== Stored statistics (from DB) ===")
stored_cf = stored_stats.get('cashflow_inprogress', {})
stored_pc = stored_stats.get('profitability_completed', {})
print(f"IP hedging={stored_cf.get('hedging_results','N/A')} farming={stored_cf.get('farming_results','N/A')} payouts={stored_cf.get('payouts','N/A')}")
print(f"CP hedging={stored_pc.get('hedging_results','N/A')} farming={stored_pc.get('farming_results','N/A')} payouts={stored_pc.get('payouts','N/A')}")

# Now check what exactly CHANGED between them - look at specific eval rows
# that might be different. Focus on rows with funded status.
P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
F_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

# Find rows where p1_hedges or funded_hedges are large and see what might differ
print(f"\n=== Rows with funded hedges (likely contributing to completed diff) ===")
for i, ev in enumerate(evaluations):
    status_p1 = str(ev.get('Status P1', '')).strip()
    status_funded = str(ev.get('Status') or ev.get('Status Funded', '')).strip()
    
    is_p1_fail = status_p1 == 'Fail'
    is_funded_fail = status_funded == 'Fail'
    is_funded_completed = status_funded == 'Completed'
    
    if not (is_p1_fail or is_funded_fail or is_funded_completed):
        continue
    
    p1 = round(sum(pc(ev.get(c)) for c in P1_COLS), 2)
    funded = round(sum(pc(ev.get(c)) for c in F_COLS), 2)
    
    # Only show rows that have significant hedge values
    if abs(p1) > 0.01 or abs(funded) > 0.01:
        acct = ev.get('Account Number', '?')
        firm = ev.get('Prop Firm', '?')
        hn = pc(ev.get('Hedge Net'))
        hn1 = pc(ev.get('Hedge Net.1'))
        
        completed_contrib = 0.0
        if is_p1_fail:
            completed_contrib += p1
        if is_funded_fail or is_funded_completed:
            completed_contrib += funded + p1
        
        print(f"  R{i}: {firm} | {acct} | P1={status_p1} F={status_funded} | p1_hedge={p1:.2f} fund_hedge={funded:.2f} | HedgeNet={hn:.2f} HedgeNet.1={hn1:.2f} | completed_contrib={completed_contrib:.2f}")
