"""Fetch FRESH evaluations using actual fetch_evaluations() and compare with Stats tab."""
import sys, io, requests
import pandas as pd
from decimal import Decimal

sys.path.insert(0, '.')
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI/edit?gid=0#gid=0"

print("Fetching fresh evaluations...")
fresh_data, notes = fetch_evaluations(SHEET_URL)
print(f"Fresh rows: {len(fresh_data)}")

# Sum hedging columns
hedge_names = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5',
               'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 
               'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
payout_names = ['Payout 1', 'Payout 2', 'Payout 3', 'Payout 4']
fee_col = 'Fee'
activation_col = 'Activation Fee'

# Compute fresh sums
fresh_hedge = Decimal('0')
for ev in fresh_data:
    for c in hedge_names:
        fresh_hedge += Decimal(str(parse_currency(ev.get(c))))

fresh_payout = Decimal('0')
for ev in fresh_data:
    for c in payout_names:
        fresh_payout += Decimal(str(parse_currency(ev.get(c))))

fresh_fee = Decimal('0')
fresh_activation = Decimal('0')
for ev in fresh_data:
    fresh_fee += Decimal(str(parse_currency(ev.get(fee_col))))
    fresh_activation += Decimal(str(parse_currency(ev.get(activation_col))))

print(f"\n=== FRESH DATA SUMS ===")
print(f"Challenge Fees:     {fresh_fee + fresh_activation} (fee={fresh_fee} + activation={fresh_activation})")
print(f"Hedging Results:    {fresh_hedge}")
print(f"Payouts:            {fresh_payout}")

print(f"\n=== STATS TAB VALUES (from XLSX just fetched) ===")
print(f"Challenge Fees:     -61234.37")
print(f"Hedging Results:    -26644.42")
print(f"Payouts:            145295.20")

print(f"\n=== DIFFERENCES ===")
print(f"Hedge diff:         {fresh_hedge - Decimal('-26644.42')}")
print(f"Payout diff:        {fresh_payout - Decimal('145295.20')}")

# Also compare stored vs fresh row counts
import sqlite3, json
conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Tyler'")
data = cur.fetchone()
conn.close()
stored = json.loads(data['evaluations'])
print(f"\nStored rows: {len(stored)}, Fresh rows: {len(fresh_data)}")

# Check if any rows were added/removed
if len(stored) != len(fresh_data):
    print("ROW COUNT MISMATCH - data has changed!")
    # Check which rows differ
    stored_firms = [e.get('Prop Firm','') + '|' + str(e.get('Fee','')) + '|' + str(e.get('Date Purchased','')) for e in stored]
    fresh_firms = [e.get('Prop Firm','') + '|' + str(e.get('Fee','')) + '|' + str(e.get('Date Purchased','')) for e in fresh_data]
    
    added = set(fresh_firms) - set(stored_firms)
    removed = set(stored_firms) - set(fresh_firms)
    if added:
        print(f"  Added rows: {len(added)}")
        for a in list(added)[:5]:
            print(f"    {a}")
    if removed:
        print(f"  Removed rows: {len(removed)}")
        for r in list(removed)[:5]:
            print(f"    {r}")
else:
    # Same row count - check if any values differ in hedge/payout columns
    hedge_diff_total = Decimal('0')
    payout_diff_total = Decimal('0')
    for i in range(len(stored)):
        for c in hedge_names:
            sv = parse_currency(stored[i].get(c))
            fv = parse_currency(fresh_data[i].get(c))
            d = Decimal(str(fv)) - Decimal(str(sv))
            if abs(d) > Decimal('0.001'):
                print(f"  Hedge diff row {i}, {c}: stored={sv}, fresh={fv}, diff={d}")
                hedge_diff_total += d
        for c in payout_names:
            sv = parse_currency(stored[i].get(c))
            fv = parse_currency(fresh_data[i].get(c))
            d = Decimal(str(fv)) - Decimal(str(sv))
            if abs(d) > Decimal('0.001'):
                print(f"  Payout diff row {i}, {c}: stored={sv}, fresh={fv}, diff={d}")
                payout_diff_total += d
    print(f"  Total hedge value changes: {hedge_diff_total}")
    print(f"  Total payout value changes: {payout_diff_total}")
