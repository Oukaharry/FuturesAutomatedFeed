
import sqlite3
import pandas as pd
import requests
from io import StringIO
import re
import json

print("Starting debug_sheet.py...")
DB_PATH = 'dashboard/dashboard.db'

def inspect_client_sheet(client_id):
    print(f"Inspecting client sheet for: {client_id}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check 'clients_data' table
    try:
        cursor.execute("SELECT identity FROM clients_data WHERE client_id = ?", (client_id,))
        row = cursor.fetchone()
    except Exception as e:
        print(f"DB Error: {e}")
        conn.close()
        return

    conn.close()
    
    if not row:
        print("Client not found in DB")
        return

    try:
        identity = json.loads(row[0])
    except:
        print("Invalid JSON in identity")
        return
        
    sheet_url = identity.get('sheet_url')
    
    if not sheet_url:
        print("No sheet_url in client identity")
        print(f"Identity keys: {identity.keys()}")
        return
        
    print(f"Found sheet URL: {sheet_url}")
    
    # Convert to CSV export URL
    if '/edit' in sheet_url:
         csv_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv').replace('/edit', '/export?format=csv')
    elif str(sheet_url).endswith('/'):
         csv_url = sheet_url + 'export?format=csv'
    else:
         csv_url = sheet_url

    print(f"Fetching CSV: {csv_url}")
    try:
        r = requests.get(csv_url, timeout=10)
        print(f"Status Code: {r.status_code}")
        
        if r.status_code == 200:
            print(f"Success ({len(r.text)} bytes)")
            
            # Simple parse
            try:
                df = pd.read_csv(StringIO(r.text), header=None)
                print("\nLast 10 rows (checking for content):")
                print(df.tail(10))
                
                print("\nSearching for 'Pro Firm' or 'Prop Firm'...")
                for i, r_row in df.head(20).iterrows():
                    values_str = str(r_row.values)
                    if 'Prop Firm' in values_str or 'Pro Firm' in values_str:
                         print(f"---> FOUND HEADER AT ROW {i}")
                         print(f"Columns: {r_row.values}")
                         
                         header_row = r_row
                         # Check if 'Account #' exists
                         for val in header_row:
                             if str(val).strip() == 'Account #':
                                 print("  -> Found 'Account #' column!")
                             if str(val).strip() == 'Account #.1':
                                 print("  -> Found 'Account #.1' column!")
                                 
            except Exception as e:
                print(f"CSV Parse Error: {e}")
        else:
            print(f"Failed HTTP {r.status_code}")
            print(f"Content: {r.text[:500]}")
    except Exception as e:
        print(f"Request Error: {e}")

if __name__ == "__main__":
    inspect_client_sheet("Jiang Quang Huang")
