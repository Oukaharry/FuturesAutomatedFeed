import requests
import pandas as pd
from io import StringIO
import re

# Original URL from user: https://docs.google.com/spreadsheets/d/10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI/edit?usp=sharing
# We convert it to export CSV format to read it
sheet_id = "10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI"
csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

print(f"Fetching from {csv_url}...")

try:
    response = requests.get(csv_url)
    response.raise_for_status()
    content = response.text
    
    print("Successfully fetched content.")
    
    # Try to read as CSV
    try:
        df = pd.read_csv(StringIO(content))
        print(f"\nDimensions: {df.shape}")
        print("\nColumns:")
        print(df.columns.tolist())
        
        print("\nFirst 10 rows:")
        print(df.head(10).to_string())
        
        # Also print raw first 50 lines to see if there are summary tables above or below
        print("\n--- RAW CONTENT HEAD (First 50 lines) ---")
        for line in content.splitlines()[:50]:
            print(line[:100]) # Truncate long lines

    except Exception as e:
        print(f"Error parsing CSV: {e}")
        print("Raw content preview:")
        print(content[:500])

except Exception as e:
    print(f"Error fetching sheet: {e}")
