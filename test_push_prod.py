"""Test push to PRODUCTION to diagnose issues."""
import requests
import json
import sys

# Test both localhost and production
targets = {
    "localhost": "http://127.0.0.1:5001",
    "production": "https://www.tradeopss.com"
}

target = sys.argv[1] if len(sys.argv) > 1 else "production"
url = targets.get(target, target)

print(f"Testing push to: {url}")

# Step 1: Test email lookup
payload = {
    "email": "302shmed@gmail.com",
    "account": {},
    "positions": [],
    "deals": [],
    "statistics": {},
    "evaluations": [],
    "aggregated_by_comment": [],
    "comment_summary": {},
    "dropdown_options": {}
}

try:
    response = requests.post(f"{url}/api/client/push", json=payload, 
                            headers={"Content-Type": "application/json"}, timeout=30)
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)[:500]}")
    except:
        print(f"Raw: {response.text[:500]}")
except requests.exceptions.ConnectionError as e:
    print(f"CONNECTION ERROR: {e}")
except requests.exceptions.Timeout:
    print("TIMEOUT - server didn't respond in 30s")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
