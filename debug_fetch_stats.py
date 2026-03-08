"""Discover Stats tab GID and fetch Stats values directly from Google Sheet."""
import requests, re, sys, io
import pandas as pd

SHEET_ID = "1EO6-a_b9uun2vwETWu8aGh67ya3nwpdLAo4F-yjc1ZI"

# Fetch the sheet HTML page to discover all tabs
html_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(html_url, headers=headers, timeout=15)

# Look for sheet names and GIDs in the HTML
# Google Sheets embeds tab info in JavaScript
gid_pattern = re.findall(r'"gid":"(\d+)".*?"name":"([^"]+)"', resp.text)
if not gid_pattern:
    # Try alternate pattern
    gid_pattern = re.findall(r'gid=(\d+)[^>]*>([^<]+)<', resp.text)

if gid_pattern:
    print("=== DISCOVERED TABS ===")
    for gid, name in gid_pattern:
        print(f"  GID {gid}: {name}")
else:
    print("Could not discover tabs from HTML. Trying known GIDs...")
    # Try common GIDs
    for test_gid in [0, 1, 2, 839895136, 1000000000]:
        csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={test_gid}"
        try:
            r = requests.get(csv_url, timeout=10)
            if r.status_code == 200 and len(r.content) > 10:
                df = pd.read_csv(io.StringIO(r.text), nrows=2)
                print(f"  GID {test_gid}: OK - cols: {list(df.columns[:5])}")
        except Exception as e:
            print(f"  GID {test_gid}: {e}")

# Try fetching the spreadsheet in XLSX format which includes all tabs
print("\n=== FETCHING XLSX TO DISCOVER ALL TABS ===")
xlsx_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
resp = requests.get(xlsx_url, timeout=30)
if resp.status_code == 200:
    xls = pd.ExcelFile(io.BytesIO(resp.content))
    print(f"Tab names: {xls.sheet_names}")
    
    if 'Stats' in xls.sheet_names:
        stats_df = pd.read_excel(xls, 'Stats', header=None)
        print(f"\n=== STATS TAB CONTENT (first 20 rows, first 5 cols) ===")
        pd.set_option('display.max_colwidth', 60)
        pd.set_option('display.width', 200)
        print(stats_df.iloc[:20, :5].to_string())
    else:
        # Check for similar names
        for name in xls.sheet_names:
            if 'stat' in name.lower():
                print(f"\nFound tab: {name}")
                stats_df = pd.read_excel(xls, name, header=None)
                print(stats_df.iloc[:20, :5].to_string())
else:
    print(f"XLSX fetch failed: {resp.status_code}")
