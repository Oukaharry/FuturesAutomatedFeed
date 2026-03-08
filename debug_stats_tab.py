"""Fetch XLSX directly and read Stats tab values."""
import requests, io, sys
import pandas as pd

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

print("Fetching XLSX...")
xlsx_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
resp = requests.get(xlsx_url, timeout=60)
print(f"Status: {resp.status_code}, Size: {len(resp.content)} bytes")

if resp.status_code == 200:
    xls = pd.ExcelFile(io.BytesIO(resp.content))
    print(f"Tabs: {xls.sheet_names}")
    
    for name in xls.sheet_names:
        if 'stat' in name.lower():
            print(f"\n=== TAB: {name} ===")
            df = pd.read_excel(xls, name, header=None)
            pd.set_option('display.max_colwidth', 80)
            pd.set_option('display.width', 200)
            pd.set_option('display.max_rows', 30)
            pd.set_option('display.max_columns', 10)
            print(df.iloc[:25, :3].to_string())
else:
    print(f"Failed: {resp.status_code}")
    print(resp.text[:500])
