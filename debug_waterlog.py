from utils.data_processor import fetch_waterlog_history
import logging

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

url = "https://docs.google.com/spreadsheets/d/10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI/edit?usp=sharing"
print(f"Testing fetch from: {url}")

try:
    history = fetch_waterlog_history(url)
    print(f"Fetched {len(history)} items.")
    if history:
        print("First 3 items:")
        for item in history[:3]:
            print(item)
except Exception as e:
    print(f"Error: {e}")
