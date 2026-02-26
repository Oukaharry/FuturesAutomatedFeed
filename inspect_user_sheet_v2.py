import requests
import io
import pandas as pd
import sys

URL = "https://docs.google.com/spreadsheets/d/10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI/export?format=csv&gid=520289647"

print(f"Fetching {URL}")
try:
    response = requests.get(URL, allow_redirects=True)
    if response.status_code == 200:
        content = response.text
        print(f"Successfully fetched {len(content)} bytes")
        
        # Print first 2500 chars raw
        print("\n--- RAW CONTENT START ---")
        print(content[:2500])
        print("--- RAW CONTENT END ---\n")
        
    else:
        print(f"Failed with status: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
