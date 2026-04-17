"""
Authenticate with Tradovate API using the NinjaTrader SSO flow that the web trader uses.
The web trader uses: NinjaTrader SSO -> short grant code -> exchangeShortGrantCode -> accessToken

But for API access, Tradovate still supports direct auth with proper app credentials.
The key insight: the DEMO API uses apiHostSuffix "-d.tradovateapi.com" (not "demo.")

Let's try all possible combinations systematically.
"""
import requests
import json

USERNAME = "FNFTHARRISONFbHey"
PASSWORD = "yvuQE10##"

# From the JS bundle analysis:
# Production: .tradovateapi.com
# Demo/Dev: -d.tradovateapi.com
# The apiHostSuffix is APPENDED to a prefix like "live" or "demo"

# All known base URLs
BASE_URLS = [
    "https://demo.tradovateapi.com/v1",
    "https://demo-d.tradovateapi.com/v1",
    "https://live.tradovateapi.com/v1",
    "https://live-d.tradovateapi.com/v1",
    # NinjaTrader
    "https://apiproxy.ninjatrader.com/v1",
    "https://apiproxy-d.ninjatrader.com/v1",
]

# Try all known app ID + cid/sec combos
APP_CONFIGS = [
    # The web trader's own credentials
    {"appId": "tradovate_trader(web)", "appVersion": "3.260403.0"},
    # Sample/documented credentials
    {"appId": "TradeOps", "appVersion": "1.0", "cid": 8, "sec": "f03741b6-f634-48d6-9308-c8fb871150c2"},
    # Just username/password
    {"appId": "TradeOps", "appVersion": "1.0"},
    # With different deviceId
    {"appId": "tradovate_trader(web)", "appVersion": "3.260403.0", "deviceId": "web-probe"},
]

for base_url in BASE_URLS:
    for app_cfg in APP_CONFIGS:
        payload = {
            "name": USERNAME,
            "password": PASSWORD,
            **app_cfg,
        }
        if "deviceId" not in payload:
            payload["deviceId"] = "probe-003"
        
        label = f"{base_url.split('//')[1].split('/')[0]} appId={app_cfg.get('appId','?')[:20]}"
        try:
            r = requests.post(f"{base_url}/auth/accesstokenrequest", json=payload, timeout=8)
            data = r.json()
            if "accessToken" in data:
                print(f"[SUCCESS] {label}")
                print(f"  URL: {base_url}")
                print(f"  Token: {data['accessToken'][:50]}...")
                print(f"  userId: {data.get('userId')}")
                print(f"  name: {data.get('name')}")
                print(f"  expiry: {data.get('expirationTime')}")
                
                # Now probe the API!
                TOKEN = data["accessToken"]
                headers = {"Authorization": f"Bearer {TOKEN}"}
                
                print(f"\n  === PROBING API WITH TOKEN ===")
                endpoints = [
                    "account/list",
                    "fill/list",
                    "order/list",
                    "position/list",
                    "cashBalance/list",
                    "cashBalanceLog/list",
                    "executionReport/list",
                    "contract/list",
                    "tradingPermission/list",
                    "marginSnapshot/list",
                    "user/list",
                    "contactInfo/list",
                    "orderStrategy/list",
                    "userProperty/list",
                    "accountRiskStatus/list",
                ]
                
                for ep in endpoints:
                    try:
                        resp = requests.get(f"{base_url}/{ep}", headers=headers, timeout=8)
                        if resp.status_code == 200:
                            data_ep = resp.json()
                            count = len(data_ep) if isinstance(data_ep, list) else "obj"
                            print(f"  [OK] {ep} -> {count} records")
                            if isinstance(data_ep, list) and data_ep:
                                print(f"       Keys: {list(data_ep[0].keys())[:10]}")
                                if ep == "account/list":
                                    for acct in data_ep[:5]:
                                        print(f"       Account: {acct.get('name')} (id={acct.get('id')}, active={acct.get('active')})")
                        else:
                            print(f"  [{resp.status_code}] {ep}")
                    except Exception as e:
                        print(f"  [ERR] {ep}: {e}")
                
                # Try fill/list with date params
                print(f"\n  === FILL HISTORY WITH DATE RANGE ===")
                # Get accounts first
                acct_resp = requests.get(f"{base_url}/account/list", headers=headers, timeout=8)
                if acct_resp.status_code == 200:
                    accounts = acct_resp.json()
                    for acct in accounts[:3]:
                        acct_id = acct["id"]
                        acct_name = acct.get("name", "?")
                        
                        # Try fills with masterid
                        fill_url = f"{base_url}/fill/ldeps?masterid={acct_id}"
                        fill_resp = requests.get(fill_url, headers=headers, timeout=8)
                        if fill_resp.status_code == 200:
                            fills = fill_resp.json()
                            print(f"  Account {acct_name}: {len(fills)} fills")
                            if fills:
                                print(f"    Fill keys: {list(fills[0].keys())}")
                                print(f"    Sample: {json.dumps(fills[0], indent=2)[:300]}")
                        
                        # Try orders with masterid
                        ord_url = f"{base_url}/order/ldeps?masterid={acct_id}"
                        ord_resp = requests.get(ord_url, headers=headers, timeout=8)
                        if ord_resp.status_code == 200:
                            orders = ord_resp.json()
                            print(f"  Account {acct_name}: {len(orders)} orders")
                            if orders:
                                print(f"    Order keys: {list(orders[0].keys())}")
                        
                        # Try cash balance
                        cb_url = f"{base_url}/cashBalance/getCashBalanceSnapshot?accountId={acct_id}"
                        cb_resp = requests.get(cb_url, headers=headers, timeout=8)
                        if cb_resp.status_code == 200:
                            cb_data = cb_resp.json()
                            print(f"  Account {acct_name} balance: {json.dumps(cb_data)[:200]}")
                
                # Done with successful auth - exit
                import sys
                sys.exit(0)
            else:
                error = data.get("errorText", str(data)[:80])
                print(f"[FAIL] {label}: {error}")
        except requests.exceptions.ConnectionError:
            print(f"[CONN] {label}: Connection refused")
        except Exception as e:
            print(f"[ERR]  {label}: {e}")

print("\n\nAll attempts failed. The credentials may only work via NinjaTrader SSO flow.")
print("Next step: Use Selenium driver.execute_script() to extract token from running browser.")
