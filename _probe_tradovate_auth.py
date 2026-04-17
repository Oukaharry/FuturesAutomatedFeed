"""Probe Tradovate via the web trader's internal API (same as browser uses)."""
import requests
import json

USERNAME = "FNFTHARRISONFbHey"
PASSWORD = "yvuQE10##"

# The web trader at trader.tradovate.com uses these internal endpoints
# Let's try multiple auth approaches

attempts = [
    # 1. Demo API - no app credentials
    {
        "name": "Demo API (no app creds)",
        "url": "https://demo.tradovateapi.com/v1/auth/accesstokenrequest",
        "body": {"name": USERNAME, "password": PASSWORD}
    },
    # 2. Demo API - with common app creds
    {
        "name": "Demo API (common cid=8)", 
        "url": "https://demo.tradovateapi.com/v1/auth/accesstokenrequest",
        "body": {
            "name": USERNAME, "password": PASSWORD,
            "appId": "SampleApp", "appVersion": "1.0", "deviceId": "d1",
            "cid": 8, "sec": "f03741b6-f634-48d6-9308-c8fb871150c2"
        }
    },
    # 3. Live API - no app creds
    {
        "name": "Live API (no app creds)",
        "url": "https://live.tradovateapi.com/v1/auth/accesstokenrequest",
        "body": {"name": USERNAME, "password": PASSWORD}
    },
    # 4. Try the simulation/demo specific URL patterns
    {
        "name": "Demo d1 API",
        "url": "https://demo-d.tradovateapi.com/v1/auth/accesstokenrequest",
        "body": {"name": USERNAME, "password": PASSWORD}
    },
    # 5. Try without version
    {
        "name": "Demo no-version",
        "url": "https://demo.tradovateapi.com/auth/accesstokenrequest",
        "body": {"name": USERNAME, "password": PASSWORD}
    },
]

for attempt in attempts:
    print(f"\n=== {attempt['name']} ===")
    print(f"  URL: {attempt['url']}")
    try:
        r = requests.post(attempt["url"], json=attempt["body"], timeout=10)
        print(f"  Status: {r.status_code}")
        try:
            data = r.json()
            # Mask token if present
            if "accessToken" in data:
                print(f"  SUCCESS! Token: {data['accessToken'][:30]}...")
                print(f"  userId: {data.get('userId')}")
                print(f"  expiry: {data.get('expirationTime')}")
            else:
                print(f"  Response: {json.dumps(data)[:300]}")
        except:
            print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"  Error: {e}")

# Also try to see what the web trader page does - check for alternative auth
print("\n\n=== Checking Tradovate Web Trader Login Flow ===")
session = requests.Session()

# The web trader might use a different auth flow
# Let's check what redirects/APIs the login page references
try:
    r = session.get("https://trader.tradovateapi.com", timeout=10, allow_redirects=True)
    print(f"  trader.tradovateapi.com -> {r.status_code} ({r.url})")
except Exception as e:
    print(f"  Error: {e}")

# Check if there's an OAuth or session-based auth 
try:
    r = session.post("https://trader.tradovate.com/api/auth/login", 
                     json={"username": USERNAME, "password": PASSWORD}, timeout=10)
    print(f"\n  trader.tradovate.com/api/auth/login -> {r.status_code}")
    print(f"  Body: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# Try the simulation URL
try:
    r = session.post("https://simulation.tradovateapi.com/v1/auth/accesstokenrequest",
                     json={"name": USERNAME, "password": PASSWORD}, timeout=10)
    print(f"\n  simulation API -> {r.status_code}")
    print(f"  Body: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")
