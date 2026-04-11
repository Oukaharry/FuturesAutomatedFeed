"""Verify the fix by recalculating Gregory Falk's stats."""
import json, sqlite3, sys
sys.path.insert(0, '.')

from utils.data_processor import fetch_evaluations, calculate_statistics

# Get stored MT5 account data
conn = sqlite3.connect('dashboard/dashboard.db')
c = conn.cursor()
c.execute("SELECT account FROM clients_data WHERE client_id = 'Gregory Falk'")
row = c.fetchone()
acct = json.loads(row[0] or '{}')
conn.close()

sheet_url = "https://docs.google.com/spreadsheets/d/1in4Z-76-GJ2URCslKafg-RIsY3XNqRLzhcZQKjgFZuQ/edit?usp=sharing"

# Fetch fresh evaluations from Google Sheet
result = fetch_evaluations(sheet_url)
if isinstance(result, tuple):
    evals, xlsx_notes = result
else:
    evals = result
    xlsx_notes = None

print(f"Fetched {len(evals)} evaluations")
print(f"XLSX notes has stats tab: {'__stats_tab__' in (xlsx_notes or {})}")
if xlsx_notes and '__stats_tab__' in xlsx_notes:
    st = xlsx_notes['__stats_tab__']
    print(f"  Stats tab hedging_results: {st.get('hedging_results')}")
    print(f"  Stats tab farming_results: {st.get('farming_results')}")

# Recalculate with the fix
stats = calculate_statistics(evals, mt5_account=acct, xlsx_notes=xlsx_notes)
hr = stats['hedging_review']
cf = stats['cashflow_inprogress']

print(f"\n=== FIXED Hedging Review ===")
print(f"  Total Deposits: {hr['total_deposits']}")
print(f"  Total Withdrawals: {hr['total_withdrawals']}")
print(f"  Current Balance: {hr['current_balance']}")
print(f"  Actual Hedging Results: {hr['actual_hedging_results']}")
print(f"  Sheet Hedging Results: {hr['sheet_hedging_results']}")
print(f"  Discrepancy: {hr['discrepancy']}")

print(f"\n=== Cashflow In-Progress ===")
print(f"  Hedging Results: {cf['hedging_results']}")
print(f"  Farming Results: {cf['farming_results']}")
print(f"  Sum: {cf['hedging_results'] + cf['farming_results']}")

print(f"\n=== Google Sheet Expected ===")
print(f"  Actual Hedging Results: -48220.92")
print(f"  Sheet Hedging Results: -49760.87")
print(f"  Discrepancy: 1539.95")

print(f"\n=== Match Check ===")
print(f"  Actual matches: {abs(hr['actual_hedging_results'] - (-48220.92)) < 0.01}")
print(f"  Sheet matches: {abs(hr['sheet_hedging_results'] - (-49760.87)) < 1.0}")
print(f"  Discrepancy matches: {abs(hr['discrepancy'] - 1539.95) < 1.0}")
