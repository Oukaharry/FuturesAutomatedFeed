import json, sys
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import TradeifyAccount

s = TradeifyAccount(debug_port=9222)
s.login()

base = "https://app-f.tradeify.co/api"

# Test the key Tradeify endpoints
endpoints = [
    "/dashboard/account-overview?hide_blown_account=true&page=1&page_size=10",
    "/dashboard/overview-pending/",
    "/dashboard/get-subscription-list?page=1&page_size=100",
    "/payouts/payout-tracking?page=1&page_size=100&start_date=2020-01-01&end_date=2030-12-31",
    "/auth/profile/",
    "/dashboard/broker-credentials",
]

for ep in endpoints:
    url = f"{base}{ep}"
    result = s._fetch_json(url)
    if result:
        txt = json.dumps(result, indent=2)[:600]
        print(f"\n{'='*60}\n{ep}:\n{txt}")
    else:
        print(f"\n--- {ep}: None")

s.close()
