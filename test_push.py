"""Test the push endpoint to diagnose why it's not working."""
import requests
import json

url = "http://127.0.0.1:5001/api/client/push"

# Simulate a minimal push from the trader app for Ed
payload = {
    "email": "302shmed@gmail.com",
    "account": {"balance": 100000, "total_deposits": 50000, "total_withdrawals": 0},
    "positions": [],
    "deals": [],
    "statistics": {},
    "evaluations": [],
    "aggregated_by_comment": [],
    "comment_summary": {},
    "dropdown_options": {}
}

try:
    response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
    except:
        print(f"Raw response: {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
