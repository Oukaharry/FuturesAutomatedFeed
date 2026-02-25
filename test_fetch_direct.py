
import sys
import os
sys.path.insert(0, os.getcwd())

try:
    from utils.data_processor import fetch_evaluations
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

url = "https://docs.google.com/spreadsheets/d/1ivVtySJKJveJHNg9Hs4kH8fTqWDgMQMOxkYCPxIMtQM/edit?gid=0#gid=0"
print(f"Testing URL: {url}")
res = fetch_evaluations(url)
if isinstance(res, tuple):
    print(f"Result count: {len(res[0])} evals, {len(res[1])} notes")
else:
    print(f"Result count: {len(res)} evals (old format)")
