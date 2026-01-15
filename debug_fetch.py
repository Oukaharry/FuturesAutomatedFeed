from utils.data_processor import fetch_evaluations
from config import settings
import datetime
import sys
import os

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

url = "https://docs.google.com/spreadsheets/d/1NX46wyWWGVOyb9IyTAEnjQUKfQ6A53Yr8MazhIJVOAY/edit?usp=sharing"

print(f"Testing fetch from: {url}")
try:
    data = fetch_evaluations(url)
    print(f"Successfully fetched {len(data)} rows.")
    if len(data) > 0:
        print("First row sample keys:", list(data[0].keys())[:5])
        print("First row sample values:", list(data[0].values())[:5])
    else:
        print("Data is empty.")
except Exception as e:
    print(f"Error: {e}")
