import requests
import pandas as pd
from io import StringIO

url = "https://docs.google.com/spreadsheets/d/1NX46wyWWGVOyb9IyTAEnjQUKfQ6A53Yr8MazhIJVOAY/export?format=csv"

try:
    print(f"Fetching {url}...")
    response = requests.get(url)
    content = response.text
    
    print(f"Content length: {len(content)} bytes")
    
    # Search for keywords
    keywords = ["Total Deposits", "Profitability", "Cashflow", "Expected Value", "Hedging Review"]
    
    print("\n--- Keyword Search ---")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw in line:
                print(f"Found '{kw}' at line {i}: {line[:100]}...")

    # Try to parse as dataframe to see structure around keywords if found
    # ...

except Exception as e:
    print(f"Error: {e}")
    header_row_idx = -1
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('Prop Firm').any():
            header_row_idx = i
            break
            
    print(f"\nHeader Row Index: {header_row_idx}")
    
    if header_row_idx != -1:
        # Get the actual columns
        df = pd.read_csv(StringIO(content), header=header_row_idx)
        print("\nColumns:")
        for i, col in enumerate(df.columns):
            print(f"{i}: {col}")

except Exception as e:
    print(e)
