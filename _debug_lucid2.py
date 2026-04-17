import json, sys
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import LucidTradingAccount

s = LucidTradingAccount(debug_port=9222)
s.login()

# Get token and key from localStorage
token = s._js("localStorage.getItem('auth_token')")
user_key = s._js("localStorage.getItem('userKey')")
email = s._js("localStorage.getItem('email')")
nickname = s._js("localStorage.getItem('nickname')")
print(f"Token: {token[:50]}..." if token else "Token: None")
print(f"UserKey: {user_key}")
print(f"Email: {email}")
print(f"Nickname: {nickname}")

base = "https://dash.lucidtrading.com/api"

# Test endpoints with Bearer token
endpoints = [
    f"/summary/{user_key}",
    f"/accounts/{user_key}",
    f"/account-summary/{user_key}",
    f"/users/{user_key}",
    f"/user/{user_key}",
    "/users/otp",
    "/affiliate/check",
    "/users/current-promo",
    "/rewards/crate-status",
    f"/billing/{user_key}",
    f"/payouts/{user_key}",
    f"/payment-history/{user_key}",
    f"/transactions/{user_key}",
]

for ep in endpoints:
    url = f"{base}{ep}"
    result = s._fetch_json_bearer(url, token)
    if result:
        txt = json.dumps(result)[:200]
        print(f"  OK  {ep}: {txt}")
    else:
        print(f"  --- {ep}: None")

s.close()
