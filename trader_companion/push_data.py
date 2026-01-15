"""
MT5 Data Pusher - Command Line Interface
Simple script for traders to push data to the dashboard from command line.
NO API KEY REQUIRED - just your email address!
"""
import sys
import os
import json
import argparse
import requests

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trader_companion.trader_app import MT5DataPusher


def lookup_client(url, email):
    """Lookup client hierarchy from email - NO API KEY."""
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/client/auth",
            json={"email": email},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return data.get("identity", {}), None
            else:
                return None, data.get("message", "Client not found")
        else:
            return None, f"API Error: {response.status_code}"
    except Exception as e:
        return None, str(e)


def push_data(url, email, account, positions, deals, statistics):
    """Push data to dashboard - NO API KEY."""
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/client/push",
            json={
                "email": email,
                "account": account,
                "positions": positions,
                "deals": deals,
                "statistics": statistics,
                "evaluations": [],
                "dropdown_options": {}
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return True, data.get("message", "Data pushed successfully")
            else:
                return False, data.get("message", "Push failed")
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)


def migrate_sheet(url, email, sheet_url):
    """Migrate data from Google Sheets."""
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/client/migrate_sheet",
            json={"email": email, "sheet_url": sheet_url},
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return True, f"Imported {data.get('records_imported', 0)} records"
            else:
                return False, data.get("message", "Migration failed")
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description='Push MT5 data to Trading Dashboard (No API Key Required!)')
    parser.add_argument('--url', default='https://ballerquotes.pythonanywhere.com', help='Dashboard URL')
    parser.add_argument('--email', required=True, help='Your registered client email')
    parser.add_argument('--sheet', help='Google Sheet URL to migrate data from')
    parser.add_argument('--mt5-login', help='MT5 account login')
    parser.add_argument('--mt5-password', help='MT5 account password')
    parser.add_argument('--mt5-server', help='MT5 server name')
    parser.add_argument('--days', type=int, default=30, help='Days of history to fetch')
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("MT5 Data Pusher (No API Key Required!)")
    print("=" * 50)
    
    # Lookup client by email first
    print(f"\n[*] Looking up client: {args.email}")
    client_info, error = lookup_client(args.url, args.email)
    
    if error:
        print(f"\n[✗] Lookup failed: {error}")
        print("    Make sure your email is registered in the system.")
        sys.exit(1)
    
    client_name = client_info.get('client', '')
    trader_name = client_info.get('trader', '')
    admin_name = client_info.get('admin', '')
    category = client_info.get('category', '')
    
    print(f"    ✓ Client: {client_name}")
    print(f"    ✓ Trader: {trader_name}")
    print(f"    ✓ Admin: {admin_name}")
    print(f"    ✓ Category: {category}")
    
    # If sheet URL provided, migrate from sheets
    if args.sheet:
        print(f"\n[*] Migrating data from Google Sheets...")
        success, msg = migrate_sheet(args.url, args.email, args.sheet)
        if success:
            print(f"\n[✓] {msg}")
        else:
            print(f"\n[✗] {msg}")
            sys.exit(1)
        print("\n[*] Done!")
        return
    
    # Otherwise, push MT5 data
    pusher = MT5DataPusher(args.url)
    
    # Connect to MT5 if credentials provided
    if args.mt5_login and args.mt5_password and args.mt5_server:
        print(f"\n[*] Connecting to MT5 account {args.mt5_login}...")
        success, msg = pusher.connect_mt5(args.mt5_login, args.mt5_password, args.mt5_server)
        print(f"    {msg}")
        
        if not success:
            print("\n[!] Failed to connect to MT5. Exiting.")
            sys.exit(1)
    else:
        # Try to connect to already running MT5
        print("\n[*] Connecting to running MT5 terminal...")
        success, msg = pusher.connect_mt5()
        print(f"    {msg}")
        
        if not success:
            print("\n[!] No MT5 connection. Provide --mt5-login, --mt5-password, --mt5-server")
            print("    Or use --sheet to migrate from Google Sheets instead.")
            sys.exit(1)
    
    # Get data
    account = pusher.get_account_info() or {}
    if account:
        print(f"\n[+] Account: #{account.get('login', 'N/A')} @ {account.get('server', 'N/A')}")
        print(f"    Balance: {account.get('balance', 0)} {account.get('currency', '')}")
        print(f"    Equity: {account.get('equity', 0)} {account.get('currency', '')}")
    
    positions = pusher.get_positions()
    deals = pusher.get_deals(days=args.days)
    statistics = pusher.calculate_statistics(deals)
    
    # Push data
    print(f"\n[*] Pushing data for client: {client_name}")
    success, msg = push_data(args.url, args.email, account, positions, deals, statistics)
    
    if success:
        print(f"\n[✓] {msg}")
    else:
        print(f"\n[✗] {msg}")
        sys.exit(1)
    
    # Disconnect
    pusher.disconnect_mt5()
    print("\n[*] Done!")


if __name__ == "__main__":
    main()
