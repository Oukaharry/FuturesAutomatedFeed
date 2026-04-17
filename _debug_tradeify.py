import json, sys
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import TradeifyAccount

s = TradeifyAccount(debug_port=9222)
s.login()

print('Connected:', s.is_connected())

# Get the broker creds response to see what data is available
creds = s._get_broker_credentials()
print("\nBroker creds (first item):")
if creds and isinstance(creds, dict):
    outer = creds.get('data', creds)
    items = outer.get('data', outer) if isinstance(outer, dict) else outer
    if isinstance(items, list) and items:
        print(json.dumps(items[0], indent=2)[:1000])
    else:
        print("items:", type(items), str(items)[:300])

# Get profile
profile = s._get_profile()
print("\nProfile data:")
if profile and isinstance(profile, dict):
    outer = profile.get('data', profile)
    pdata = outer.get('data', outer) if isinstance(outer, dict) else outer
    if isinstance(pdata, dict):
        print(json.dumps(pdata, indent=2)[:1000])

# Try some other endpoints that might have balance data
base = "https://api-b.tradeify.co"
print("\n--- Testing billing/account endpoints ---")
endpoints = [
    "/api/dashboard/get-subscription-list?page=1&page_size=100",
    "/api/payouts/payout-tracking?page=1&page_size=100&start_date=2020-01-01&end_date=2030-12-31",
    "/api/dashboard/account-overview",
    "/api/dashboard/get-account-balance",
    "/api/dashboard/account-info",
]
for ep in endpoints:
    url = f"{base}{ep}"
    result = s._fetch_json(url)
    if result:
        print(f"\n  OK  {ep}: {json.dumps(result)[:300]}")
    else:
        print(f"\n  --- {ep}: None")

s.close()
