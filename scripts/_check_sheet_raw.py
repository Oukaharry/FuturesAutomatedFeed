"""Fetch raw Google Sheet headers for Ed to check if Prop Progress columns exist"""
import requests
import pandas as pd
from io import StringIO

# Ed's sheet URL - get from DB
from dashboard.database import get_connection
import json

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT identity FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    identity = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    sheet_url = identity.get('sheet_url', '') if isinstance(identity, dict) else ''
    print(f"Sheet URL: {sheet_url[:80]}...")

if sheet_url:
    # Convert to CSV export URL
    if '/edit' in sheet_url:
        csv_url = sheet_url.split('/edit')[0] + '/export?format=csv'
    elif '/pub' in sheet_url:
        csv_url = sheet_url.split('/pub')[0] + '/export?format=csv'
    else:
        csv_url = sheet_url + '/export?format=csv'
    
    print(f"CSV URL: {csv_url[:80]}...")
    
    resp = requests.get(csv_url, timeout=30)
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    
    if resp.status_code == 200:
        content = resp.text
        
        # Find the header row (contains "Prop Firm")
        lines = content.split('\n')
        header_line_idx = -1
        for i, line in enumerate(lines[:20]):
            if 'Prop Firm' in line:
                header_line_idx = i
                print(f"Header row found at line {i}")
                break
        
        if header_line_idx >= 0:
            # Parse with that header row
            df = pd.read_csv(StringIO(content), header=header_line_idx)
            cols = list(df.columns)
            print(f"Total columns: {len(cols)}")
            
            # Check for Progress columns
            progress_cols = [c for c in cols if 'rogress' in str(c).lower()]
            print(f"Progress columns: {progress_cols}")
            
            # Show farming-related columns only
            farming_cols = [c for c in cols if any(x in str(c) for x in ['Prop Day', 'Progress', 'Hedge Day', 'Farming'])]
            print(f"Farming columns ({len(farming_cols)}):")
            for c in farming_cols[:20]:
                print(f"  {c}")
        else:
            print("No header row found, showing first lines:")
            for i, line in enumerate(lines[:5]):
                print(f"  [{i}] {line[:200]}")
