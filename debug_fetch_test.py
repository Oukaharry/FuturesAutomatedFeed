
import pandas as pd
import requests
from io import StringIO
import re

def clean_data_structure(data):
    if isinstance(data, dict):
        return {k: clean_data_structure(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_data_structure(item) for item in data]
    elif isinstance(data, float):
        if pd.isna(data):
            return None
        return data
    else:
        return data

def fetch_evaluations(sheet_url):
    """
    Fetches evaluation data from a public Google Sheet CSV export.
    Finds the header row dynamically by looking for 'Prop Firm'.
    """
    try:
        # Ensure we get CSV format
        if '/edit' in sheet_url:
            csv_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv').replace('/edit', '/export?format=csv')
        else:
            csv_url = sheet_url

        print(f"DEBUG: Using CSV URL: {csv_url}")

        response = requests.get(csv_url)
        print(f"DEBUG: Response status: {response.status_code}")
        if response.status_code != 200:
             print(f"DEBUG: Fetch failed. {response.text}")
             return []
        
        response.raise_for_status()
        
        print(f"DEBUG: Response content sample: {response.text[:200]}")

        # Read without header first to find the correct row
        try:
             df = pd.read_csv(StringIO(response.text), header=None)
        except Exception as e:
             print(f"DEBUG: Pandas read failed: {e}")
             return []
        
        # Find the row that contains "Prop Firm" in the first few columns
        header_idx = -1
        print("DEBUG: Checking rows for 'Prop Firm'")
        for i, row in df.head(10).iterrows():
            row_str = row.astype(str)
            print(f"DEBUG: Row {i}: {row_str.values[:5]}")
            if row_str.str.contains('Prop Firm', case=False, na=False).any():
                header_idx = i
                print(f"DEBUG: Found 'Prop Firm' at row {i}")
                break
        
        if header_idx != -1:
            # Reload with correct header
            df = pd.read_csv(StringIO(response.text), header=header_idx)
            print(f"DEBUG: Reloaded with header at {header_idx}, columns: {df.columns.tolist()[:10]}")
            
            # Clean up columns (remove unnamed, strip whitespace)
            df.columns = [str(c).strip() for c in df.columns]
            
            # Simple check if Prop Firm is in columns
            if 'Prop Firm' in df.columns:
                print("DEBUG: 'Prop Firm' found in columns.")
                return df.to_dict(orient='records')
            else:
                 print("DEBUG: 'Prop Firm' NOT found in columns despite setting header.")
        else:
             print("DEBUG: Could not find 'Prop Firm' in first 10 rows.")

        return []
    except Exception as e:
        print(f"Error fetching sheet: {e}")
        return []

url = "https://docs.google.com/spreadsheets/d/1MXdZmlfD4OjiWhN_KHmJtyNsgq9hQQsJ0RpvTdsDguo/edit?usp=sharing"
fetch_evaluations(url)
