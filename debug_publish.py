import sys
import os
import requests
import datetime
import pandas as pd
from config import settings
from utils.data_processor import fetch_evaluations, calculate_statistics, extract_unique_values, clean_data_structure

def debug_publish():
    print("--- Starting Debug Publish ---")
    
    # Mock MT5 Data (since we might not be able to connect to MT5 in this script easily without the terminal path issues)
    # But we can try to use the connector if needed. For now, let's assume empty MT5 data to test the Sheet part.
    trades_data = []
    positions_data = []
    account_data = {"balance": 10000, "login": 123456, "profit": 0}
    
    # 4. Get Evaluations
    evaluations_data = []
    sheet_url = settings.SHEET_URL
    
    if sheet_url:
        try:
            print(f"Fetching Sheet from: {sheet_url}")
            evaluations_data = fetch_evaluations(sheet_url)
            print(f"Fetched {len(evaluations_data)} rows from Sheet.")
            if len(evaluations_data) > 0:
                print("First row sample:", evaluations_data[0])
        except Exception as e:
            print(f"Error fetching evaluations: {e}")
            import traceback
            traceback.print_exc()
    
    # 5. Calculate Statistics
    print("Calculating statistics...")
    try:
        stats_data = calculate_statistics(evaluations_data, mt5_deals=trades_data, mt5_account=account_data)
        print("Statistics calculated.")
    except Exception as e:
        print(f"Error calculating statistics: {e}")
        import traceback
        traceback.print_exc()
        stats_data = {}

    # 6. Extract Dropdown Options
    dropdown_options = extract_unique_values(evaluations_data)

    payload = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "deals": trades_data,
        "positions": positions_data,
        "account": account_data,
        "evaluations": evaluations_data,
        "statistics": stats_data,
        "dropdown_options": dropdown_options
    }
    
    payload = clean_data_structure(payload)
    
    try:
        print("Sending data to dashboard...")
        response = requests.post("http://localhost:5001/api/update_data", json=payload)
        print(f"Response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error publishing: {e}")

if __name__ == "__main__":
    debug_publish()
