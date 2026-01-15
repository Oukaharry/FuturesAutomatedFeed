"""Compare Tsubasa Google Sheet vs Dashboard Database"""
import sys
sys.path.insert(0, '..')
from utils.data_processor import fetch_evaluations, calculate_statistics
from database import get_connection
import json

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/edit?usp=sharing'

print("=" * 60)
print("FETCHING FROM GOOGLE SHEET...")
print("=" * 60)

evals = fetch_evaluations(SHEET_URL)
print(f"Records fetched: {len(evals)}")

sheet_stats = calculate_statistics(evals)

print("\n=== GOOGLE SHEET STATS ===")
prof = sheet_stats['profitability_completed']
print(f"PROFITABILITY (Completed):")
print(f"  Challenge Fees:  ${prof['challenge_fees']:,.2f}")
print(f"  Hedging Results: ${prof['hedging_results']:,.2f}")
print(f"  Farming Results: ${prof['farming_results']:,.2f}")
print(f"  Payouts:         ${prof['payouts']:,.2f}")
print(f"  Net Profit:      ${prof['net_profit']:,.2f}")

cash = sheet_stats['cashflow_inprogress']
print(f"\nCASHFLOW (In Progress):")
print(f"  Challenge Fees:  ${cash['challenge_fees']:,.2f}")
print(f"  Hedging Results: ${cash['hedging_results']:,.2f}")
print(f"  Farming Results: ${cash['farming_results']:,.2f}")
print(f"  Payouts:         ${cash['payouts']:,.2f}")
print(f"  Net Profit:      ${cash['net_profit']:,.2f}")

et = sheet_stats['eval_totals']
print(f"\nEVAL TOTALS:")
print(f"  Running: {et['total_running']}, Passed: {et['total_passed']}, Failed: {et['total_failed']}")

ft = sheet_stats['funded_totals']
print(f"\nFUNDED TOTALS:")
print(f"  Not Started: {ft['not_started']}, Ongoing: {ft['ongoing']}, Failed: {ft['failed']}, Completed: {ft['completed']}")

print("\n" + "=" * 60)
print("FETCHING FROM DATABASE (Tsubasa)...")
print("=" * 60)

with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT statistics, evaluations FROM clients_data WHERE client_id = 'Tsubasa'")
    row = cursor.fetchone()
    
    if row:
        db_stats = json.loads(row[0]) if row[0] else {}
        db_evals = json.loads(row[1]) if row[1] else []
        
        print(f"Records in DB: {len(db_evals)}")
        
        print("\n=== DATABASE STATS ===")
        prof = db_stats.get('profitability_completed', {})
        print(f"PROFITABILITY (Completed):")
        print(f"  Challenge Fees:  ${prof.get('challenge_fees', 0):,.2f}")
        print(f"  Hedging Results: ${prof.get('hedging_results', 0):,.2f}")
        print(f"  Farming Results: ${prof.get('farming_results', 0):,.2f}")
        print(f"  Payouts:         ${prof.get('payouts', 0):,.2f}")
        print(f"  Net Profit:      ${prof.get('net_profit', 0):,.2f}")
        
        cash = db_stats.get('cashflow_inprogress', {})
        print(f"\nCASHFLOW (In Progress):")
        print(f"  Challenge Fees:  ${cash.get('challenge_fees', 0):,.2f}")
        print(f"  Hedging Results: ${cash.get('hedging_results', 0):,.2f}")
        print(f"  Farming Results: ${cash.get('farming_results', 0):,.2f}")
        print(f"  Payouts:         ${cash.get('payouts', 0):,.2f}")
        print(f"  Net Profit:      ${cash.get('net_profit', 0):,.2f}")
        
        et = db_stats.get('eval_totals', {})
        print(f"\nEVAL TOTALS:")
        print(f"  Running: {et.get('total_running', 0)}, Passed: {et.get('total_passed', 0)}, Failed: {et.get('total_failed', 0)}")
        
        ft = db_stats.get('funded_totals', {})
        print(f"\nFUNDED TOTALS:")
        print(f"  Not Started: {ft.get('not_started', 0)}, Ongoing: {ft.get('ongoing', 0)}, Failed: {ft.get('failed', 0)}, Completed: {ft.get('completed', 0)}")
    else:
        print("No Tsubasa record found in database!")

print("\n" + "=" * 60)
print("COMPARISON")
print("=" * 60)

# Compare key metrics
def compare(name, sheet_val, db_val):
    match = abs(sheet_val - db_val) < 0.01 if isinstance(sheet_val, float) else sheet_val == db_val
    status = "MATCH" if match else "MISMATCH"
    if isinstance(sheet_val, float):
        print(f"  {name}: Sheet=${sheet_val:,.2f} vs DB=${db_val:,.2f} [{status}]")
    else:
        print(f"  {name}: Sheet={sheet_val} vs DB={db_val} [{status}]")

if row:
    print("\nProfitability:")
    sp = sheet_stats['profitability_completed']
    dp = db_stats.get('profitability_completed', {})
    compare("Challenge Fees", sp['challenge_fees'], dp.get('challenge_fees', 0))
    compare("Hedging Results", sp['hedging_results'], dp.get('hedging_results', 0))
    compare("Farming Results", sp['farming_results'], dp.get('farming_results', 0))
    compare("Payouts", sp['payouts'], dp.get('payouts', 0))
    compare("Net Profit", sp['net_profit'], dp.get('net_profit', 0))
    
    print("\nCashflow:")
    sc = sheet_stats['cashflow_inprogress']
    dc = db_stats.get('cashflow_inprogress', {})
    compare("Challenge Fees", sc['challenge_fees'], dc.get('challenge_fees', 0))
    compare("Hedging Results", sc['hedging_results'], dc.get('hedging_results', 0))
    compare("Farming Results", sc['farming_results'], dc.get('farming_results', 0))
    compare("Payouts", sc['payouts'], dc.get('payouts', 0))
    compare("Net Profit", sc['net_profit'], dc.get('net_profit', 0))
    
    print("\nEval Totals:")
    se = sheet_stats['eval_totals']
    de = db_stats.get('eval_totals', {})
    compare("Running", se['total_running'], de.get('total_running', 0))
    compare("Passed", se['total_passed'], de.get('total_passed', 0))
    compare("Failed", se['total_failed'], de.get('total_failed', 0))
    
    print("\nFunded Totals:")
    sf = sheet_stats['funded_totals']
    df = db_stats.get('funded_totals', {})
    compare("Not Started", sf['not_started'], df.get('not_started', 0))
    compare("Ongoing", sf['ongoing'], df.get('ongoing', 0))
    compare("Failed", sf['failed'], df.get('failed', 0))
    compare("Completed", sf['completed'], df.get('completed', 0))
    
    print(f"\nRecord count: Sheet={len(evals)} vs DB={len(db_evals)} [{'MATCH' if len(evals) == len(db_evals) else 'MISMATCH'}]")
