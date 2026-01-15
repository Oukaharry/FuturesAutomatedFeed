"""Test script to verify dashboard can receive data"""
import requests
import json

API_KEY = 'tk_3NcE5MJ9rZHIiejTIE_XQ-WCtCA1H7-DpAYhnmy7rKM'
URL = 'http://127.0.0.1:5001/api/update_data'

test_data = {
    'identity': {
        'admin': 'Philip',
        'trader': 'Philip',
        'client': 'Chris'
    },
    'account': {
        'balance': 10000.00,
        'equity': 10500.00,
        'profit': 500.00,
        'margin': 1000.00,
        'free_margin': 9500.00
    },
    'positions': [
        {'symbol': 'EURUSD', 'volume': 0.1, 'profit': 150.00, 'type': 'buy'},
        {'symbol': 'GBPUSD', 'volume': 0.05, 'profit': -25.00, 'type': 'sell'}
    ],
    'deals': [
        {'symbol': 'EURUSD', 'volume': 0.1, 'profit': 75.00, 'time': '2026-01-09 10:00:00'}
    ],
    'statistics': {
        'total_trades': 25,
        'win_rate': 0.68,
        'profit_factor': 1.85
    }
}

print("Testing dashboard data update...")
print(f"URL: {URL}")
print(f"API Key: {API_KEY[:20]}...")

try:
    response = requests.post(URL, json=test_data, headers={'X-API-Key': API_KEY})
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        print("\n✅ Dashboard is ready to receive data!")
    else:
        print("\n❌ There was an issue sending data")
        
except requests.exceptions.ConnectionError:
    print("\n❌ Could not connect to server. Make sure the dashboard is running on port 5001")
except Exception as e:
    print(f"\n❌ Error: {e}")
