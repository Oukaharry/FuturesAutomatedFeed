#!/usr/bin/env python3
"""
Test your deployed dashboard
Usage: python test_deployed.py https://yourusername.pythonanywhere.com
"""

import sys
import requests

if len(sys.argv) < 2:
    print("Usage: python test_deployed.py <dashboard_url>")
    print("Example: python test_deployed.py https://harrytrader.pythonanywhere.com")
    sys.exit(1)

url = sys.argv[1].rstrip('/')

print(f"Testing dashboard at: {url}\n")

# Test health endpoint
try:
    response = requests.get(f"{url}/api/health", timeout=10)
    if response.status_code == 200:
        data = response.json()
        print("[OK] Dashboard is online!")
        print(f"  Status: {data.get('status')}")
        print(f"  Clients: {data.get('clients_count')}")
    else:
        print(f"[FAIL] Health check failed: {response.status_code}")
except Exception as e:
    print(f"[FAIL] Connection failed: {e}")
    print("\nMake sure:")
    print("  1. Dashboard is deployed and running")
    print("  2. URL is correct (should start with https://)")
    print("  3. You clicked 'Reload' on PythonAnywhere")
