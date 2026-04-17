"""
Deep-dive into Tradovate REST API endpoints.
Uses the auth token from sessionStorage to probe available endpoints.
Read-only — no modifications.
"""
import json, urllib.request, websocket, time, ssl

CDP_PORT = 9222

def get_tabs():
    return json.loads(urllib.request.urlopen(f'http://localhost:{CDP_PORT}/json').read())

def send_cdp(ws, method, params=None, timeout=5):
    msg_id = int(time.time() * 1000) % 1000000
    msg = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
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

def api_get(base_url, endpoint, token, params=None):
    """Make a GET request to the Tradovate API."""
    url = f"{base_url}{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        data = json.loads(resp.read())
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:200]
        return {"_error": e.code, "_message": body}
    except Exception as e:
        return {"_error": str(e)}


if __name__ == "__main__":
    tabs = get_tabs()
    tradovate_tab = next((t for t in tabs if 'trader.tradovate.com' in t.get('url', '')), None)
    
    if not tradovate_tab:
        print("No Tradovate tab found!")
        exit(1)
    
    ws_url = tradovate_tab["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=10)
    
    # Extract auth state from sessionStorage
    auth_script = "sessionStorage.getItem('api_authenticator_state')"
    resp = send_cdp(ws, "Runtime.evaluate", {"expression": auth_script, "returnByValue": True})
    auth_state = json.loads(resp["result"]["value"])
    
    token = auth_state.get("token", "")
    environment = auth_state.get("environment", "demo")
    username = auth_state.get("username", "")
    
    print(f"Environment: {environment}")
    print(f"Username: {username}")
    print(f"Token: {token[:50]}...")
    
    # Determine base URL based on environment
    if environment == "demo":
        base_url = "https://demo.tradovateapi.com/v1"
    else:
        base_url = "https://live.tradovateapi.com/v1"
    
    # Also try live since the page uses live for some endpoints
    live_base = "https://live.tradovateapi.com/v1"
    
    ws.close()
    
    print(f"\nBase URL: {base_url}")
    print(f"Live URL: {live_base}")
    
    # ========================================================================
    # PROBE ALL RELEVANT ENDPOINTS
    # ========================================================================
    
    print("\n" + "="*80)
    print("1. ACCOUNT ENDPOINTS")
    print("="*80)
    
    # Account list
    accounts = api_get(base_url, "/account/list", token)
    if isinstance(accounts, list):
        print(f"\n  /account/list → {len(accounts)} accounts:")
        for a in accounts:
            print(f"    ID={a.get('id')} Name={a.get('name')} Nickname={a.get('nickname','')} "
                  f"Active={a.get('active')} MarginType={a.get('marginAccountType','')} "
                  f"LegalStatus={a.get('legalStatus','')}")
            # Print all keys for first account
            if a == accounts[0]:
                print(f"    ALL KEYS: {list(a.keys())}")
    else:
        print(f"  /account/list → {accounts}")
    
    # Also try live account list
    live_accounts = api_get(live_base, "/account/list", token)
    if isinstance(live_accounts, list) and live_accounts != accounts:
        print(f"\n  LIVE /account/list → {len(live_accounts)} accounts:")
        for a in live_accounts:
            print(f"    ID={a.get('id')} Name={a.get('name')} Active={a.get('active')}")
    
    # Get account IDs for further queries
    account_ids = [a["id"] for a in accounts] if isinstance(accounts, list) else []
    
    print("\n" + "="*80)
    print("2. CASH BALANCE / BALANCE HISTORY")
    print("="*80)
    
    for acc_id in account_ids[:3]:
        # Cash balance
        cb = api_get(base_url, f"/cashBalance/getCashBalanceSnapshot", token, {"accountId": str(acc_id)})
        print(f"\n  /cashBalance/getCashBalanceSnapshot?accountId={acc_id} →")
        if isinstance(cb, dict) and "_error" not in cb:
            for k, v in cb.items():
                print(f"    {k}: {v}")
        else:
            print(f"    {cb}")
    
    # Cash balance list
    cb_list = api_get(base_url, "/cashBalance/list", token)
    print(f"\n  /cashBalance/list →")
    if isinstance(cb_list, list):
        print(f"    {len(cb_list)} entries")
        for cb in cb_list[:5]:
            print(f"    {cb}")
    else:
        print(f"    {cb_list}")
    
    print("\n" + "="*80)
    print("3. FILL / TRADE HISTORY")
    print("="*80)
    
    for acc_id in account_ids[:2]:
        # Fills
        fills = api_get(base_url, "/fill/list", token)
        print(f"\n  /fill/list →")
        if isinstance(fills, list):
            print(f"    {len(fills)} fills")
            for f in fills[:3]:
                print(f"    {f}")
            if fills:
                print(f"    ALL KEYS: {list(fills[0].keys())}")
        else:
            print(f"    {fills}")
        
        # Fill deps (by account)
        fill_deps = api_get(base_url, f"/fill/deps", token, {"masterid": str(acc_id)})
        print(f"\n  /fill/deps?masterid={acc_id} →")
        if isinstance(fill_deps, list):
            print(f"    {len(fill_deps)} fills for account {acc_id}")
            for f in fill_deps[:3]:
                ts = f.get('timestamp', '')
                price = f.get('price', '')
                qty = f.get('qty', '')
                side = f.get('action', '')
                contract = f.get('contractId', '')
                print(f"      {ts} | {side} {qty} @ {price} (contract={contract})")
        else:
            print(f"    {fill_deps}")
    
    print("\n" + "="*80)
    print("4. ORDER HISTORY")
    print("="*80)
    
    for acc_id in account_ids[:2]:
        orders = api_get(base_url, f"/order/deps", token, {"masterid": str(acc_id)})
        print(f"\n  /order/deps?masterid={acc_id} →")
        if isinstance(orders, list):
            print(f"    {len(orders)} orders")
            for o in orders[:3]:
                print(f"      {o.get('timestamp','')} | {o.get('action','')} {o.get('orderQty','')} "
                      f"status={o.get('ordStatus','')} contract={o.get('contractId','')}")
            if orders:
                print(f"    ALL KEYS: {list(orders[0].keys())}")
        else:
            print(f"    {orders}")
    
    print("\n" + "="*80)
    print("5. POSITION HISTORY")
    print("="*80)
    
    for acc_id in account_ids[:2]:
        positions = api_get(base_url, f"/position/deps", token, {"masterid": str(acc_id)})
        print(f"\n  /position/deps?masterid={acc_id} →")
        if isinstance(positions, list):
            print(f"    {len(positions)} positions")
            for p in positions[:3]:
                print(f"      contract={p.get('contractId','')} netPos={p.get('netPos','')} "
                      f"netPrice={p.get('netPrice','')} timestamp={p.get('timestamp','')}")
            if positions:
                print(f"    ALL KEYS: {list(positions[0].keys())}")
        else:
            print(f"    {positions}")
    
    print("\n" + "="*80)
    print("6. TRADE LOG / EXECUTION REPORT")
    print("="*80)
    
    # Try various history endpoints
    history_endpoints = [
        "/executionReport/list",
        "/executionReport/deps",
        "/tradingPermission/list",
    ]
    for ep in history_endpoints:
        params = {"masterid": str(account_ids[0])} if "deps" in ep else {}
        result = api_get(base_url, ep, token, params if params else None)
        print(f"\n  {ep} →")
        if isinstance(result, list):
            print(f"    {len(result)} items")
            for item in result[:2]:
                print(f"    {json.dumps(item)[:200]}")
        else:
            print(f"    {result}")
    
    print("\n" + "="*80)
    print("7. CONTRACT / PRODUCT INFO")
    print("="*80)
    
    contracts = api_get(base_url, "/contract/list", token)
    if isinstance(contracts, list):
        print(f"  /contract/list → {len(contracts)} contracts")
        # Show first few
        for c in contracts[:3]:
            print(f"    ID={c.get('id')} Name={c.get('name')} Status={c.get('status','')}")
    else:
        print(f"  /contract/list → {contracts}")
    
    print("\n" + "="*80)
    print("8. DAILY PROFIT / ACCOUNT REPORTS (probing)")
    print("="*80)
    
    # Try various report-like endpoints
    report_endpoints = [
        "/account/find",
        "/userAccountPositionLimit/list",
        "/userAccountRiskParameter/list",
        "/marginSnapshot/list",
        "/tradingPermission/list",
        "/accountRiskStatus/deps",
        "/userAccountAutoLiq/list",
    ]
    
    for ep in report_endpoints:
        params = {}
        if "deps" in ep:
            params = {"masterid": str(account_ids[0])}
        elif "find" in ep:
            params = {"name": accounts[0]["name"]} if isinstance(accounts, list) and accounts else {}
        
        result = api_get(base_url, ep, token, params if params else None)
        if isinstance(result, list):
            count = len(result)
            preview = json.dumps(result[0])[:150] if result else "[]"
            print(f"  {ep} → {count} items | {preview}")
        elif isinstance(result, dict) and "_error" not in result:
            print(f"  {ep} → {json.dumps(result)[:200]}")
        else:
            err = result.get("_error", "") if isinstance(result, dict) else result
            print(f"  {ep} → ERROR: {err}")
    
    print("\n" + "="*80)
    print("9. USER INFO")
    print("="*80)
    
    user_resp = api_get(live_base, "/user/item", token, {"id": "4911485"})
    if isinstance(user_resp, dict) and "_error" not in user_resp:
        print(f"  User ID: {user_resp.get('id')}")
        print(f"  Name: {user_resp.get('name')}")
        print(f"  Email: {user_resp.get('email','')}")
        print(f"  ALL KEYS: {list(user_resp.keys())}")
    
    # Organization
    org_resp = api_get(live_base, "/organization/item", token, {"id": "31"})
    if isinstance(org_resp, dict) and "_error" not in org_resp:
        print(f"  Organization: {org_resp.get('name')} (ID={org_resp.get('id')})")
    
    print("\n" + "="*80)
    print("10. WEBSOCKET REAL-TIME ENDPOINTS")
    print("="*80)
    
    print("  Tradovate uses WebSocket for real-time data:")
    if environment == "demo":
        print("  - wss://demo.tradovateapi.com/v1/websocket")
        print("  - wss://md.tradovateapi.com/v1/websocket (market data)")
    else:
        print("  - wss://live.tradovateapi.com/v1/websocket")
        print("  - wss://md.tradovateapi.com/v1/websocket (market data)")
    print("  Auth: Send 'authorize\\n<p_ticket>\\n<token>' after connecting")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"  Environment: {environment}")
    print(f"  Username: {username}")
    print(f"  Accounts: {len(account_ids)}")
    print(f"  Token length: {len(token)} chars")
    print(f"  Token valid: {'yes' if not any(isinstance(r, dict) and r.get('_error') == 401 for r in [accounts]) else 'expired'}")
