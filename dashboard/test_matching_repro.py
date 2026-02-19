
import sys
import os
import datetime
import logging

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

from dashboard.app import update_evaluations_from_aggregated_data

# Mock Logger
class MockLogger:
    def info(self, msg): print(f"INFO: {msg}")
    def error(self, msg): print(f"ERROR: {msg}")

# Setup data based on user logs
# Session 74020 (Start: 2026-01-19 08:47:31)
# Session 74018 (Start: 2026-01-23 11:27:03)

# Mock Deals
# We need to create raw_deals that will form these sessions.
# We need deals with comments like '74020_CH1' or similar to trigger the logic.

def create_deals():
    base_time = datetime.datetime(2026, 1, 19, 8, 47, 31).timestamp()
    
    deals = []
    
    # Session 1: 74020
    deals.append({
        'time': base_time,
        'profit': 100,
        'comment': '74020_CH1',
        'type': 'BUY'
    })
    
    # Session 2: 74018 (A few days later)
    time2 = datetime.datetime(2026, 1, 23, 11, 27, 3).timestamp()
    deals.append({
        'time': time2,
        'profit': 200,
        'comment': '74018_CH1',
        'type': 'BUY'
    })
    
    return deals

# Mock Evaluations
# We don't know exactly what Armin's evaluations look like in the DB, 
# but let's assume they might have 'Account Number' as '74020' or 'MFFU74020' or something similar.
# The user said "Check why we are not matching any account".
# Maybe the evaluations have empty account numbers? Or int vs str issues?

def create_evaluations():
    return [
        {'id': 1, 'Account Number': '74020', 'Date Purchased': '2026-01-18'}, # Should match first
        {'id': 2, 'Account Number': 74018, 'Date Purchased': '2026-01-20'},   # Int instead of str?
        {'id': 3, 'Account Number': 'MFFU80594', 'Date Purchased': '2026-01-20'}, # Prefix?
        {'id': 4, 'Account Number': '', 'Date Purchased': '2026-01-20'},      # Empty
    ]

if __name__ == "__main__":
    print("Running matching test...")
    evals = create_evaluations()
    deals = create_deals()
    
    updated_evals, log = update_evaluations_from_aggregated_data(evals, raw_deals=deals)
    
    print("\n--- Match Log ---")
    for l in log:
        print(l)
        
    print("\n--- Updated Evals ---")
    for e in updated_evals:
        print(f"ID {e['id']} ({e['Account Number']}): Hedge Result={e.get('Hedge Result')}")
