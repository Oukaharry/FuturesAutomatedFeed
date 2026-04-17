"""
Tradovate API returns p-ticket = MFA required.
The credentials ARE valid on demo.tradovateapi.com but need a second factor.
Let's check the full response and understand the MFA flow.
"""
import requests
import json

USERNAME = "FNFTHARRISONFbHey"
PASSWORD = "yvuQE10##"

BASE = "https://demo.tradovateapi.com/v1"

# Step 1: Initial auth
payload = {
    "name": USERNAME,
    "password": PASSWORD,
    "appId": "TradeOps",
    "appVersion": "1.0",
    "deviceId": "probe-004",
    "cid": 8,
    "sec": "f03741b6-f634-48d6-9308-c8fb871150c2"
}

print("=== Step 1: Initial Auth Request ===")
r = requests.post(f"{BASE}/auth/accesstokenrequest", json=payload, timeout=15)
data = r.json()
print(f"Status: {r.status_code}")
print(f"Full response:\n{json.dumps(data, indent=2)}")

p_ticket = data.get("p-ticket")
if p_ticket:
    print(f"\n>>> MFA Challenge! p-ticket present (length={len(p_ticket)})")
    print(f">>> This means credentials are VALID but 2FA is required")
    
    # Check what 2FA methods are available
    # The Tradovate API supports device approval / TOTP
    # We can also try to use a device token to bypass MFA
    
    # Step 2: Try to complete MFA with device trust
    # The web trader stores a deviceId that can be trusted
    print("\n=== Step 2: Attempting with trusted device ===")
    
    # Try with a specific device token
    payload2 = {
        "name": USERNAME,
        "password": PASSWORD,
        "appId": "TradeOps",
        "appVersion": "1.0",
        "deviceId": "TradeOps-probe",
        "cid": 8,
        "sec": "f03741b6-f634-48d6-9308-c8fb871150c2",
        # Some APIs accept p-ticket + verification code
        "p-ticket": p_ticket,
    }
    r2 = requests.post(f"{BASE}/auth/accesstokenrequest", json=payload2, timeout=15)
    print(f"Status: {r2.status_code}")
    print(f"Response:\n{json.dumps(r2.json(), indent=2)}")
    
    # Step 3: Check available MFA types
    print("\n=== Step 3: Check MFA options ===")
    mfa_endpoints = [
        f"{BASE}/auth/otp",
        f"{BASE}/auth/secondMarketDataAccessTokenRequest",
    ]
    headers = {"Authorization": f"Bearer {p_ticket}"}
    for ep in mfa_endpoints:
        try:
            r3 = requests.post(ep, json={"p-ticket": p_ticket}, timeout=10, headers=headers)
            print(f"\n  POST {ep.split('/v1/')[1]}:")
            print(f"  Status: {r3.status_code}")
            print(f"  Response: {r3.text[:200]}")
        except Exception as e:
            print(f"  {ep}: {e}")

    # Step 4: Try without 2FA by not including sec (some configurations skip 2FA for certain apps)
    print("\n=== Step 4: Try minimal auth (no cid/sec) ===")
    payload_min = {
        "name": USERNAME,
        "password": PASSWORD,
    }
    r4 = requests.post(f"{BASE}/auth/accesstokenrequest", json=payload_min, timeout=15)
    print(f"Status: {r4.status_code}")
    print(f"Response:\n{json.dumps(r4.json(), indent=2)}")
    
else:
    if "accessToken" in data:
        print("\n>>> No MFA required - got token directly!")
    else:
        print(f"\n>>> Auth failed: {data.get('errorText', 'Unknown error')}")
