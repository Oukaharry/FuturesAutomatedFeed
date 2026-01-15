from utils.data_processor import fetch_evaluations
import pandas as pd
import numpy as np
import json

url = "https://docs.google.com/spreadsheets/d/1NX46wyWWGVOyb9IyTAEnjQUKfQ6A53Yr8MazhIJVOAY/edit?usp=sharing"

print(f"Testing fetch from: {url}")
try:
    data = fetch_evaluations(url)
    print(f"Successfully fetched {len(data)} rows.")
    
    # Check for JSON compliance
    try:
        json_str = json.dumps(data)
        print("JSON serialization successful.")
    except Exception as e:
        print(f"JSON serialization failed: {e}")
        
        # Find the culprit
        for i, row in enumerate(data):
            for k, v in row.items():
                try:
                    json.dumps({k: v})
                except:
                    print(f"Row {i}, Key {k}, Value {v}, Type {type(v)}")

except Exception as e:
    print(f"Error: {e}")
