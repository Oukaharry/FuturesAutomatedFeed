"""
Focused Tradovate REST API probe.
Uses token from the open CDP-managed Tradovate session.
Tests ALL documented Tradovate API v1 endpoints.
"""
import json, urllib.request, websocket, time, ssl, base64

CDP_PORT = 9222

def get_tabs():
    return json.loads(urllib.request.urlopen(f'http://localhost:{CDP_PORT}/json').read())

def send_cdp(ws, method, params=None, timeout=5):
    msg_id = int(time.time() * 1000) % 1000000
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ws.settimeout(min(1, deadline - time.time()))
            resp = json.loads(ws.recv())
            if resp.get("id") == msg_id:
                return resp.get("result", {})
        except websocket.WebSocketTimeoutException:
            continue
    return None

def api_get(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_msg": e.read().decode('utf-8', errors='replace')[:300]}
    except Exception as e:
        return {"_error": str(e)}

def api_post(url, token, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_msg": e.read().decode('utf-8', errors='replace')[:300]}
    except Exception as e:
        return {"_error": str(e)}


if __name__ == "__main__":
    # Get token from open Tradovate tab
    tabs = get_tabs()
    trado_tab = next((t for t in tabs if 'tradovate' in t.get('url','').lower() 
                       and t.get('webSocketDebuggerUrl')), None)
    
    if not trado_tab:
        print("No Tradovate tab found on CDP port 9222")
        exit(1)
    
    ws = websocket.create_connection(trado_tab["webSocketDebuggerUrl"], timeout=10)
    resp = send_cdp(ws, "Runtime.evaluate", {
        "expression": "sessionStorage.getItem('api_authenticator_state')",
        "returnByValue": True
    })
    ws.close()
    
    auth = json.loads(resp["result"]["value"])
    token = auth["token"]
    env = auth["environment"]
    username = auth["username"]
    
    # Decode token to get user ID
    payload = token.split('.')[1] + '=='
    claims = json.loads(base64.urlsafe_b64decode(payload))
    user_id = claims.get("sub", "")
    
    BASE = f"https://{env}.tradovateapi.com/v1"
    LIVE = "https://live.tradovateapi.com/v1"
    
    print(f"User: {username} | Env: {env} | UserID: {user_id}")
    print(f"Base: {BASE}")
    print()

    # ================================================================
    # COMPREHENSIVE ENDPOINT PROBE
    # ================================================================
    
    # --- Entity Discovery ---
    # Tradovate API follows a pattern: /entity/list, /entity/item, /entity/deps, /entity/ldeps, /entity/find
    # Let's systematically probe all known entity types
    
    entities_to_probe = [
        # Core trading
        "account", "order", "fill", "position", "contract", "product",
        "exchange", "currency", "currencyRate",
        # Balance
        "cashBalance", "cashBalanceLog",
        # Risk
        "marginSnapshot", "accountRiskStatus", "userAccountRiskParameter",
        "userAccountPositionLimit", "userAccountAutoLiq",
        # Reports
        "executionReport", "fillFee",
        # User/Org
        "user", "organization", "tradingPermission",
        # Subscriptions
        "tradovateSubscription", "tradovateSubscriptionPlan",
        # Entitlements
        "entitlement",
        # Admin
        "adminAlertSignal", "adminAlert",
        # Properties
        "property", "userProperty",
        # Misc
        "contactInfo", "marketDataSubscription", "marketDataSubscriptionExchangeScope",
        "userPlugin", "orderStrategy", "orderStrategyLink",
        "fillPair", "contractMaturity", "productSession",
        "spreadDefinition", "command", "commandReport",
        "alert", "alertSignal",
        "userSession", "userSessionStats",
    ]
    
    print("=" * 90)
    print("ENTITY ENDPOINT DISCOVERY")
    print("=" * 90)
    
    working_entities = {}
    
    for entity in entities_to_probe:
        result = api_get(f"{BASE}/{entity}/list", token)
        if isinstance(result, list):
            working_entities[entity] = result
            count = len(result)
            if count > 0:
                keys = list(result[0].keys())
                print(f"  ✅ {entity}/list → {count} items | Keys: {keys}")
            else:
                print(f"  ⬜ {entity}/list → 0 items (endpoint works, no data)")
        elif isinstance(result, dict) and result.get("_error") == 404:
            print(f"  ❌ {entity}/list → 404 NOT FOUND")
        elif isinstance(result, dict) and result.get("_error") == 403:
            print(f"  🔒 {entity}/list → 403 FORBIDDEN")
        else:
            err = result.get("_error", "?") if isinstance(result, dict) else "?"
            msg = str(result.get("_msg", ""))[:60] if isinstance(result, dict) else ""
            print(f"  ⚠️  {entity}/list → {err} {msg}")
    
    # Also try on LIVE base if we're in demo
    if env == "demo":
        print(f"\n  --- CROSS-CHECK ON LIVE API ---")
        for entity in ["account", "user", "organization"]:
            result = api_get(f"{LIVE}/{entity}/list", token)
            if isinstance(result, list):
                print(f"  ✅ LIVE {entity}/list → {len(result)} items")
                if result:
                    for item in result[:3]:
                        print(f"       {json.dumps(item)[:150]}")
            else:
                err = result.get("_error", "?") if isinstance(result, dict) else "?"
                print(f"  ❌ LIVE {entity}/list → {err}")
    
    # ================================================================
    # DEPS QUERIES (per-account data)
    # ================================================================
    account_list = working_entities.get("account", [])
    if not account_list:
        # Try user deps
        print(f"\n  No accounts in {env}. Trying /account/deps for user {user_id}...")
        account_list = api_get(f"{LIVE}/account/deps", token, ) or []
        if not isinstance(account_list, list):
            account_list = []
    
    if account_list:
        acc = account_list[0]
        acc_id = acc["id"]
        acc_name = acc.get("name", "?")
        
        print(f"\n{'='*90}")
        print(f"PER-ACCOUNT DATA (Account: {acc_name}, ID={acc_id})")
        print(f"{'='*90}")
        
        deps_entities = [
            "fill", "order", "position", "cashBalance", "cashBalanceLog",
            "executionReport", "fillFee", "marginSnapshot",
            "accountRiskStatus", "userAccountRiskParameter",
            "userAccountPositionLimit", "userAccountAutoLiq",
            "fillPair", "orderStrategy", "orderStrategyLink",
        ]
        
        for entity in deps_entities:
            result = api_get(f"{BASE}/{entity}/deps?masterid={acc_id}", token)
            if isinstance(result, list):
                count = len(result)
                if count > 0:
                    keys = list(result[0].keys())
                    print(f"  ✅ {entity}/deps → {count} items | Keys: {keys}")
                    # Show samples for key entities
                    if entity in ("fill", "cashBalance", "cashBalanceLog", "executionReport", "fillPair", "position"):
                        for item in result[:3]:
                            print(f"       {json.dumps(item)[:180]}")
                else:
                    print(f"  ⬜ {entity}/deps → 0 items")
            else:
                err = result.get("_error", "?") if isinstance(result, dict) else "?"
                print(f"  ❌ {entity}/deps → {err}")
    
    # ================================================================
    # SPECIAL ENDPOINTS (non-standard patterns)
    # ================================================================
    print(f"\n{'='*90}")
    print("SPECIAL / CUSTOM ENDPOINTS")
    print(f"{'='*90}")
    
    special_endpoints = [
        # Auth
        (f"{LIVE}/auth/getsocialappids", "GET", None),
        (f"{LIVE}/support/gettimestamp", "GET", None),
        (f"{LIVE}/user/getconnectedapplications", "GET", None),
        # Contract
        (f"{BASE}/contract/rollcontracts", "GET", None),
        (f"{BASE}/contract/find?name=ESM6", "GET", None),
        (f"{BASE}/contract/find?name=ESZ5", "GET", None),
        (f"{BASE}/contract/find?name=NQM6", "GET", None),
        # Product
        (f"{BASE}/product/find?name=ES", "GET", None),
        (f"{BASE}/product/find?name=NQ", "GET", None),
        # Cash balance snapshot
    ]
    
    if account_list:
        acc_id = account_list[0]["id"]
        special_endpoints.append(
            (f"{BASE}/cashBalance/getCashBalanceSnapshot?accountId={acc_id}", "GET", None)
        )
    
    for url, method, body in special_endpoints:
        if method == "GET":
            result = api_get(url, token)
        else:
            result = api_post(url, token, body)
        
        if isinstance(result, dict) and "_error" in result:
            print(f"  ❌ {url.split('/v1/')[-1]} → {result['_error']}")
        elif isinstance(result, list):
            print(f"  ✅ {url.split('/v1/')[-1]} → {len(result)} items")
            if result:
                print(f"       Sample: {json.dumps(result[0])[:150]}")
        else:
            print(f"  ✅ {url.split('/v1/')[-1]} → {json.dumps(result)[:180]}")
    
    # ================================================================
    # WEBSOCKET REAL-TIME STREAM INFO
    # ================================================================
    print(f"\n{'='*90}")
    print("WEBSOCKET REAL-TIME STREAMS")
    print(f"{'='*90}")
    print(f"  Endpoint: wss://{env}.tradovateapi.com/v1/websocket")
    print(f"  Market Data: wss://md.tradovateapi.com/v1/websocket")
    print(f"  Auth protocol: Send authorize\\n0\\n\\n{token[:20]}...")
    print(f"  Subscriptions available:")
    print(f"    - user/syncrequest (account updates)")
    print(f"    - md/subscribeQuote (live quotes)")
    print(f"    - md/subscribeHistogram")
    print(f"    - md/subscribeDOM")
    print(f"    - md/getChart (historical chart data)")
    
    # ================================================================
    # SUMMARY
    # ================================================================
    print(f"\n{'='*90}")
    print("AUTOMATION OPPORTUNITIES SUMMARY")
    print(f"{'='*90}")
    
    print(f"""
  AUTH:
    - Token available in sessionStorage['api_authenticator_state']
    - Can also authenticate directly: POST {LIVE}/auth/accesstokenrequest
      Body: {{"name": "<username>", "password": "<password>", "appId": "Tradovate Trader", "appVersion": "0.0.1", "deviceId": "...", "cid": 8, "sec": "..."}}
    - Token is JWT (EdDSA signed), contains sub=userId, expires periodically

  ACCOUNTS:
    - {len(account_list)} account(s) found in {env}
    - /account/list returns all accounts with: id, name, nickname, active, marginAccountType, legalStatus
    
  FILLS (Trade History):
    - /fill/deps?masterid=<accountId> — all fills for an account
    - Fields: timestamp, action (Buy/Sell), qty, price, contractId, orderId
    - This is the EXACT data from "Fills" tab in Account Reports
    
  CASH BALANCE:
    - /cashBalance/getCashBalanceSnapshot?accountId=<id> — current balance
    - /cashBalanceLog/deps?masterid=<id> — balance change history
    - Fields: timestamp, tradeDate, deltaAmount, totalAmount, currencyId
    - This is the "Account Balance History" data
    
  ORDERS:
    - /order/deps?masterid=<id> — order history per account
    - Fields: timestamp, action, orderQty, ordStatus, contractId, etc.
    
  POSITIONS:
    - /position/deps?masterid=<id> — current/recent positions
    
  CONTRACTS:
    - /contract/find?name=ESM6 — look up contract by name
    - /contract/item?id=<id> — get contract details
    
  RISK:
    - /accountRiskStatus/deps — drawdown limits, loss limits
    - /userAccountRiskParameter/deps — risk parameters
    
  REAL-TIME:
    - WebSocket at wss://{env}.tradovateapi.com/v1/websocket
    - Can stream fills, positions, balance updates in real-time
""")
