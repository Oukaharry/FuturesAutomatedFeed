"""
Test script to compare statistics from Google Sheet vs Dashboard calculations.
This helps identify discrepancies in the formulas.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.data_processor import fetch_evaluations, calculate_statistics, parse_currency
# Use the correct sheet URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/1vtuGcTe8ys44wHCJGJr6VoImeh8q0beaKkZMt0hd3VU/edit?usp=sharing"
import json

def test_stats():
    print("=" * 70)
    print("STATISTICS COMPARISON TEST")
    print("=" * 70)
    
    # Fetch data from Google Sheet
    print(f"\n[1] Fetching data from Google Sheet...")
    print(f"    URL: {SHEET_URL[:50]}...")
    
    evaluations = fetch_evaluations(SHEET_URL)
    
    if not evaluations:
        print("    ❌ Failed to fetch evaluations!")
        return
    
    print(f"    ✅ Fetched {len(evaluations)} evaluation records")
    
    # Show sample data
    print(f"\n[2] Sample Record (first row):")
    if evaluations:
        sample = evaluations[0]
        for key in ['Prop Firm', 'Account Size', 'Fee', 'Status P1', 'Status', 
                    'Hedge Net', 'Hedge Net.1', 'Payout 1', 'Farming Net']:
            val = sample.get(key, 'N/A')
            print(f"    {key}: {val}")
    
    # Calculate statistics
    print(f"\n[3] Calculating statistics...")
    stats = calculate_statistics(evaluations)
    
    # Display key statistics
    print("\n" + "=" * 70)
    print("PROFITABILITY - COMPLETED (Failed/Completed accounts)")
    print("=" * 70)
    prof = stats['profitability_completed']
    print(f"    Challenge Fees:    ${prof['challenge_fees']:,.2f}")
    print(f"    Hedging Results:   ${prof['hedging_results']:,.2f}")
    print(f"    Farming Results:   ${prof['farming_results']:,.2f}")
    print(f"    Payouts:           ${prof['payouts']:,.2f}")
    print(f"    Net Profit:        ${prof['net_profit']:,.2f}")
    
    print("\n" + "=" * 70)
    print("CASHFLOW - IN PROGRESS (Active accounts)")
    print("=" * 70)
    cash = stats['cashflow_inprogress']
    print(f"    Challenge Fees:    ${cash['challenge_fees']:,.2f}")
    print(f"    Hedging Results:   ${cash['hedging_results']:,.2f}")
    print(f"    Farming Results:   ${cash['farming_results']:,.2f}")
    print(f"    Payouts:           ${cash['payouts']:,.2f}")
    print(f"    Net Profit:        ${cash['net_profit']:,.2f}")
    
    print("\n" + "=" * 70)
    print("EVALUATION TOTALS")
    print("=" * 70)
    et = stats['eval_totals']
    print(f"    Total Running:     {et['total_running']}")
    print(f"    Not Started:       {et['not_started']}")
    print(f"    Ongoing:           {et['ongoing']}")
    print(f"    Total Passed:      {et['total_passed']}")
    print(f"    Total Failed:      {et['total_failed']}")
    print(f"    Avg Net Failed:    ${et['avg_net_failed']:,.2f}")
    print(f"    Funded Rate:       {et['funded_rate']:.1f}%")
    
    print("\n" + "=" * 70)
    print("FUNDED TOTALS")
    print("=" * 70)
    ft = stats['funded_totals']
    print(f"    Not Started:       {ft['not_started']}")
    print(f"    Ongoing:           {ft['ongoing']}")
    print(f"    Failed:            {ft['failed']}")
    print(f"    Completed:         {ft['completed']}")
    print(f"    Avg Net Failed:    ${ft['avg_net_failed']:,.2f}")
    print(f"    Avg Net Completed: ${ft['avg_net_completed']:,.2f}")
    print(f"    Total Funding:     ${ft['total_funding']:,.2f}")
    
    print("\n" + "=" * 70)
    print("PER-FIRM BREAKDOWN (Evaluation)")
    print("=" * 70)
    for firm, data in stats['evaluation_data'].items():
        if data['total_running'] > 0 or data['total_passed'] > 0 or data['total_failed'] > 0:
            print(f"\n    {firm}:")
            print(f"        Running: {data['total_running']} | Passed: {data['total_passed']} | Failed: {data['total_failed']}")
            print(f"        Funded Rate: {data.get('funded_rate', 0):.1f}%")
    
    print("\n" + "=" * 70)
    print("RAW DATA SUMS (For Manual Verification)")
    print("=" * 70)
    
    # Manual calculation for verification
    total_fees = 0.0
    total_hedge_net = 0.0
    total_hedge_net_1 = 0.0
    total_payouts = 0.0
    total_farming = 0.0
    
    status_counts = {}
    status_p1_counts = {}
    
    for ev in evaluations:
        total_fees += parse_currency(ev.get('Fee', 0)) + parse_currency(ev.get('Activation Fee', 0))
        total_hedge_net += parse_currency(ev.get('Hedge Net', 0))
        total_hedge_net_1 += parse_currency(ev.get('Hedge Net.1', 0))
        total_farming += parse_currency(ev.get('Farming Net', 0))
        
        for i in range(1, 5):
            total_payouts += parse_currency(ev.get(f'Payout {i}', 0))
        
        # Count statuses
        s = str(ev.get('Status', '')).lower()
        sp1 = str(ev.get('Status P1', '')).lower()
        
        status_counts[s] = status_counts.get(s, 0) + 1
        status_p1_counts[sp1] = status_p1_counts.get(sp1, 0) + 1
    
    print(f"\n    Raw Fee Total:           ${total_fees:,.2f}")
    print(f"    Raw Hedge Net Total:     ${total_hedge_net:,.2f}")
    print(f"    Raw Hedge Net.1 Total:   ${total_hedge_net_1:,.2f}")
    print(f"    Raw Hedge Combined:      ${total_hedge_net + total_hedge_net_1:,.2f}")
    print(f"    Raw Payouts Total:       ${total_payouts:,.2f}")
    print(f"    Raw Farming Total:       ${total_farming:,.2f}")
    
    print(f"\n    Status P1 Counts: {status_p1_counts}")
    print(f"    Status (Funded) Counts: {status_counts}")
    
    # Grand Total
    grand_total = (total_payouts + total_hedge_net + total_hedge_net_1 + total_farming) - total_fees
    print(f"\n    GRAND TOTAL NET: ${grand_total:,.2f}")
    
    # Verify against calculated
    calc_total = prof['net_profit'] + cash['net_profit']
    print(f"    Calculated Total (Prof + Cash): ${calc_total:,.2f}")
    
    if abs(grand_total - calc_total) < 0.01:
        print(f"\n    ✅ TOTALS MATCH!")
    else:
        print(f"\n    ⚠️ DISCREPANCY: ${grand_total - calc_total:,.2f}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    
    return stats

if __name__ == "__main__":
    test_stats()
