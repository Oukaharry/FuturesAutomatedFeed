import sys
import os

# Add the current directory to sys.path so we can import dashboard
sys.path.append(os.getcwd())

from dashboard.utils.sheet_helper import fetch_stats_data

data = fetch_stats_data()
if data:
    print(f"Total rows: {len(data)}")
    for i, row in enumerate(data):
        # Print only first 30 rows to identify sections
        if i < 30:
            print(f"Row {i}: {row}")
else:
    print("Failed to fetch data")
