"""
Example: Integrating Dashboard API Client with MT5 Connector
This shows how to modify your existing MT5 automation to send data to the cloud dashboard.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import time
from threading import Thread
from dashboard.api_client import DashboardAPIClient


# ============================================================================
# CONFIGURATION - Each trader sets these values
# ============================================================================
DASHBOARD_URL = "https://harrytrader.pythonanywhere.com"  # Your hosted dashboard URL
API_KEY = "YOUR_API_KEY_HERE"  # Get this from admin using manage_api_keys.py
CLIENT_ID = "Chris"  # This trader's client name
UPDATE_INTERVAL = 300  # Send updates every 5 minutes (300 seconds)


# ============================================================================
# Initialize Dashboard Client
# ============================================================================
dashboard_client = DashboardAPIClient(DASHBOARD_URL, API_KEY, CLIENT_ID)


# ============================================================================
# Data Collection Functions
# ============================================================================

def collect_account_data():
    """Collect account information from MT5."""
    account_info = mt5.account_info()
    if not account_info:
        return None
    
    return {
        "balance": account_info.balance,
        "equity": account_info.equity,
        "margin": account_info.margin,
        "free_margin": account_info.margin_free,
        "margin_level": account_info.margin_level,
        "profit": account_info.profit,
        "currency": account_info.currency,
        "leverage": account_info.leverage,
        "server": account_info.server,
        "name": account_info.name,
        "login": account_info.login
    }


def collect_positions():
    """Collect current open positions from MT5."""
    positions = mt5.positions_get()
    if not positions:
        return []
    
    positions_list = []
    for pos in positions:
        positions_list.append({
            "ticket": pos.ticket,
            "time": pos.time,
            "symbol": pos.symbol,
            "type": "BUY" if pos.type == 0 else "SELL",
            "volume": pos.volume,
            "price": pos.price_open,
            "current_price": pos.price_current,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": pos.profit,
            "swap": pos.swap,
            "commission": pos.commission,
            "comment": pos.comment,
            "magic": pos.magic
        })
    
    return positions_list


def collect_deals(days_back=7):
    """Collect deal history from MT5."""
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)
    
    deals = mt5.history_deals_get(start_time, end_time)
    if not deals:
        return []
    
    deals_list = []
    for deal in deals:
        deals_list.append({
            "ticket": deal.ticket,
            "order": deal.order,
            "time": deal.time,
            "symbol": deal.symbol,
            "type": "BUY" if deal.type == 0 else "SELL",
            "entry": "IN" if deal.entry == 0 else "OUT",
            "volume": deal.volume,
            "price": deal.price,
            "profit": deal.profit,
            "swap": deal.swap,
            "commission": deal.commission,
            "fee": deal.fee,
            "comment": deal.comment,
            "magic": deal.magic
        })
    
    return deals_list


def collect_orders():
    """Collect current pending orders from MT5."""
    orders = mt5.orders_get()
    if not orders:
        return []
    
    orders_list = []
    for order in orders:
        orders_list.append({
            "ticket": order.ticket,
            "time": order.time_setup,
            "symbol": order.symbol,
            "type": order.type_description,
            "volume": order.volume_initial,
            "price": order.price_open,
            "sl": order.sl,
            "tp": order.tp,
            "comment": order.comment,
            "magic": order.magic
        })
    
    return orders_list


# ============================================================================
# Dashboard Update Functions
# ============================================================================

def send_to_dashboard():
    """
    Collect all MT5 data and send to dashboard.
    This function should be called periodically.
    """
    try:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sending data to dashboard...")
        
        # Collect all data
        account = collect_account_data()
        positions = collect_positions()
        deals = collect_deals(days_back=7)
        
        # Send data using individual endpoints (recommended for large datasets)
        if account:
            result = dashboard_client.push_account_data(account)
            if result.get("status") == "success":
                print("  ✓ Account data sent")
            else:
                print(f"  ✗ Account data failed: {result.get('message')}")
        
        result = dashboard_client.push_positions(positions)
        if result.get("status") == "success":
            print(f"  ✓ Positions sent ({len(positions)} positions)")
        else:
            print(f"  ✗ Positions failed: {result.get('message')}")
        
        result = dashboard_client.push_deals(deals)
        if result.get("status") == "success":
            print(f"  ✓ Deals sent ({len(deals)} deals)")
        else:
            print(f"  ✗ Deals failed: {result.get('message')}")
        
        # Alternative: Send all data at once (for small datasets)
        # all_data = {
        #     "identity": {
        #         "admin": "Philip",
        #         "trader": "Philip",
        #         "client": CLIENT_ID
        #     },
        #     "account": account,
        #     "positions": positions,
        #     "deals": deals
        # }
        # result = dashboard_client.push_all_data(all_data)
        
        print(f"  Dashboard update completed\n")
        
    except Exception as e:
        print(f"  ✗ Dashboard update error: {e}\n")


def dashboard_update_loop():
    """
    Background thread that sends updates to dashboard periodically.
    Runs continuously in the background.
    """
    print(f"\n{'='*60}")
    print("DASHBOARD AUTO-UPDATE STARTED")
    print(f"{'='*60}")
    print(f"Dashboard URL: {DASHBOARD_URL}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Update interval: {UPDATE_INTERVAL} seconds")
    print(f"{'='*60}\n")
    
    # Test connection first
    health = dashboard_client.health_check()
    if health.get("status") == "ok":
        print("✓ Dashboard connection successful\n")
    else:
        print(f"✗ Dashboard connection failed: {health}\n")
        print("Will keep trying...\n")
    
    while True:
        try:
            send_to_dashboard()
        except Exception as e:
            print(f"Dashboard update loop error: {e}")
        
        time.sleep(UPDATE_INTERVAL)


# ============================================================================
# Integration with Your Existing Code
# ============================================================================

def start_dashboard_integration():
    """
    Call this function from your main.py to start dashboard integration.
    This starts a background thread that sends updates automatically.
    """
    # Start background thread
    thread = Thread(target=dashboard_update_loop, daemon=True)
    thread.start()
    print("Dashboard integration thread started")
    return thread


# ============================================================================
# Example Usage in main.py
# ============================================================================

if __name__ == "__main__":
    """
    Example of how to integrate this into your existing main.py
    """
    
    # Initialize MT5
    if not mt5.initialize():
        print("MT5 initialization failed")
        quit()
    
    print("MT5 initialized successfully")
    
    # Start dashboard integration (runs in background)
    start_dashboard_integration()
    
    # Your existing trading logic continues here...
    # The dashboard updates will happen automatically in the background
    
    try:
        while True:
            # Your main trading loop
            # ... your existing code ...
            
            time.sleep(60)  # Your main loop delay
            
    except KeyboardInterrupt:
        print("\nShutting down...")
        mt5.shutdown()


# ============================================================================
# Manual Update Example
# ============================================================================

def manual_update_example():
    """
    If you prefer to manually trigger updates (e.g., after specific events),
    you can call send_to_dashboard() directly instead of using the automatic loop.
    """
    
    # Initialize MT5
    mt5.initialize()
    
    # Do some trading...
    # ... your code ...
    
    # Manually send update to dashboard
    send_to_dashboard()
    
    # Continue trading...
    # ... your code ...
    
    mt5.shutdown()
