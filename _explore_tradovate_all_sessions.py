"""
Deep analysis of ALL Tradovate sessions — extracts auth tokens from every
open Tradovate tab and probes their APIs independently.
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
    url = f"{base_url}{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:200]
        return {"_error": e.code, "_message": body}
    except Exception as e:
        return {"_error": str(e)}

def api_post(base_url, endpoint, token, body=None):
    url = f"{base_url}{endpoint}"
    data = json.dumps(body or {}).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')[:200]
        return {"_error": e.code, "_message": body_text}
    except Exception as e:
        return {"_error": str(e)}


if __name__ == "__main__":
    tabs = get_tabs()
    all_tabs = tabs  # We'll scan ALL tabs for auth state
    
    print("=" * 80)
    print(f"Scanning all {len(all_tabs)} tabs for Tradovate auth tokens...")
    print("=" * 80)
    
    sessions = []  # (username, env, token, base_url, tab_title)
    
    for tab in all_tabs:
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
            # Try sessionStorage for Tradovate auth
            resp = send_cdp(ws, "Runtime.evaluate", {
                "expression": "sessionStorage.getItem('api_authenticator_state')",
                "returnByValue": True
            }, timeout=3)
            ws.close()
            
            val = resp.get("result", {}).get("value") if resp else None
            if not val or val == "null":
                continue
            
            auth = json.loads(val)
            token = auth.get("token", "")
            env = auth.get("environment", "")
            user = auth.get("username", "")
            
            if token and user:
                base = f"https://{env}.tradovateapi.com/v1" if env in ("demo", "live") else None
                if base:
                    # Dedup by username
                    if not any(s[0] == user for s in sessions):
                        sessions.append((user, env, token, base, tab.get("title", "?")))
                        print(f"  Found: {user} ({env}) — {tab.get('title','')[:60]}")
        except Exception as e:
            continue
    
    print(f"\nTotal unique sessions: {len(sessions)}")
    
    for username, env, token, base_url, title in sessions:
        print(f"\n{'='*80}")
        print(f"SESSION: {username} ({env})")
        print(f"Tab: {title[:80]}")
        print(f"Base: {base_url}")
        print(f"{'='*80}")
        
        # 1. ACCOUNTS
        accounts = api_get(base_url, "/account/list", token)
        if isinstance(accounts, list):
            print(f"\n  ACCOUNTS ({len(accounts)}):")
            for a in accounts:
                print(f"    ID={a.get('id')} | Name={a.get('name')} | Nick={a.get('nickname','')} "
                      f"| Active={a.get('active')} | MarginType={a.get('marginAccountType','')}")
            if accounts:
                print(f"    [KEYS: {list(accounts[0].keys())}]")
        else:
            print(f"  ACCOUNTS: {accounts}")
            # Try live too
            if env == "demo":
                live_accts = api_get("https://live.tradovateapi.com/v1", "/account/list", token)
                if isinstance(live_accts, list) and live_accts:
                    print(f"  LIVE ACCOUNTS ({len(live_accts)}):")
                    for a in live_accts:
                        print(f"    ID={a.get('id')} Name={a.get('name')}")
                    accounts = live_accts
        
        account_ids = [a["id"] for a in accounts] if isinstance(accounts, list) else []
        
        if not account_ids:
            print("  No accounts found — skipping data endpoints")
            
            # But still check user info
            # Extract user ID from token (sub claim)
            try:
                import base64
                payload = token.split('.')[1]
                # Add padding
                payload += '=' * (4 - len(payload) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload))
                user_id = claims.get("sub", "")
                print(f"  Token subject (user ID): {user_id}")
                
                user_info = api_get("https://live.tradovateapi.com/v1", f"/user/item", token, {"id": user_id})
                if isinstance(user_info, dict) and "_error" not in user_info:
                    print(f"  User: {user_info.get('name')} | Email: {user_info.get('email','')} | Org: {user_info.get('organizationId','')}")
                    org_id = user_info.get("organizationId")
                    if org_id:
                        org = api_get("https://live.tradovateapi.com/v1", "/organization/item", token, {"id": str(org_id)})
                        if isinstance(org, dict) and "_error" not in org:
                            print(f"  Organization: {org.get('name')} (ID={org.get('id')})")
            except Exception as e:
                print(f"  Token decode error: {e}")
            continue
        
        # 2. CASH BALANCE for each account
        print(f"\n  CASH BALANCES:")
        for acc_id in account_ids[:5]:
            acc_name = next((a["name"] for a in accounts if a["id"] == acc_id), "?")
            cb = api_get(base_url, "/cashBalance/getCashBalanceSnapshot", token, {"accountId": str(acc_id)})
            if isinstance(cb, dict) and "_error" not in cb:
                print(f"    Account {acc_name} (ID={acc_id}):")
                for k, v in cb.items():
                    print(f"      {k}: {v}")
            else:
                print(f"    Account {acc_name}: {cb}")
        
        # 3. FILLS for each account
        print(f"\n  FILLS (trade executions):")
        for acc_id in account_ids[:3]:
            acc_name = next((a["name"] for a in accounts if a["id"] == acc_id), "?")
            fills = api_get(base_url, "/fill/deps", token, {"masterid": str(acc_id)})
            if isinstance(fills, list):
                print(f"    Account {acc_name}: {len(fills)} fills")
                for f in fills[:5]:
                    print(f"      {f.get('timestamp','')} | {f.get('action','')} {f.get('qty','')} "
                          f"@ {f.get('price','')} | P&L={f.get('pnl','?')} | Contract={f.get('contractId','')}")
                if fills:
                    print(f"      [KEYS: {list(fills[0].keys())}]")
            else:
                print(f"    Account {acc_name}: {fills}")
        
        # 4. ORDERS for each account
        print(f"\n  ORDERS:")
        for acc_id in account_ids[:3]:
            acc_name = next((a["name"] for a in accounts if a["id"] == acc_id), "?")
            orders = api_get(base_url, "/order/deps", token, {"masterid": str(acc_id)})
            if isinstance(orders, list):
                print(f"    Account {acc_name}: {len(orders)} orders")
                for o in orders[:3]:
                    print(f"      {o.get('timestamp','')} | {o.get('action','')} {o.get('orderQty','')} "
                          f"| Status={o.get('ordStatus','')} | Contract={o.get('contractId','')}")
                if orders:
                    print(f"      [KEYS: {list(orders[0].keys())}]")
            else:
                print(f"    Account {acc_name}: {orders}")
        
        # 5. POSITIONS for each account
        print(f"\n  POSITIONS:")
        for acc_id in account_ids[:3]:
            acc_name = next((a["name"] for a in accounts if a["id"] == acc_id), "?")
            positions = api_get(base_url, "/position/deps", token, {"masterid": str(acc_id)})
            if isinstance(positions, list):
                print(f"    Account {acc_name}: {len(positions)} positions")
                for p in positions[:3]:
                    print(f"      Contract={p.get('contractId','')} NetPos={p.get('netPos','')} "
                          f"Price={p.get('netPrice','')} Timestamp={p.get('timestamp','')}")
                if positions:
                    print(f"      [KEYS: {list(positions[0].keys())}]")
            else:
                print(f"    Account {acc_name}: {positions}")

        # 6. Try specific history/report endpoints
        print(f"\n  PROBING ADDITIONAL ENDPOINTS:")
        probe_endpoints = [
            ("/executionReport/list", None),
            ("/executionReport/deps", {"masterid": str(account_ids[0])}),
            ("/userAccountPositionLimit/list", None),
            ("/userAccountRiskParameter/list", None),
            ("/userAccountRiskParameter/deps", {"masterid": str(account_ids[0])}),
            ("/marginSnapshot/list", None),
            ("/marginSnapshot/deps", {"masterid": str(account_ids[0])}),
            ("/tradingPermission/list", None),
            ("/accountRiskStatus/list", None),
            ("/accountRiskStatus/deps", {"masterid": str(account_ids[0])}),
            ("/userAccountAutoLiq/list", None),
            ("/userAccountAutoLiq/deps", {"masterid": str(account_ids[0])}),
            ("/cashBalanceLog/list", None),
            ("/cashBalanceLog/deps", {"masterid": str(account_ids[0])}),
            ("/fillFee/list", None),
            ("/fillFee/deps", {"masterid": str(account_ids[0])}),
        ]
        
        for ep, params in probe_endpoints:
            result = api_get(base_url, ep, token, params)
            if isinstance(result, list):
                status = f"{len(result)} items"
                if result:
                    keys = list(result[0].keys())
                    sample = json.dumps(result[0])[:120]
                    print(f"    ✅ {ep} → {status} | Keys: {keys}")
                    print(f"       Sample: {sample}")
                else:
                    print(f"    ⬚ {ep} → 0 items")
            elif isinstance(result, dict) and "_error" not in result:
                print(f"    ✅ {ep} → {json.dumps(result)[:150]}")
            else:
                err = result.get("_error", "") if isinstance(result, dict) else str(result)
                msg = result.get("_message", "") if isinstance(result, dict) else ""
                print(f"    ❌ {ep} → {err} {msg[:80]}")
        
        # 7. Try POST-based history queries (some Tradovate endpoints use POST for date ranges)
        print(f"\n  PROBING POST-BASED HISTORY ENDPOINTS:")
        post_endpoints = [
            ("/cashBalance/getCashBalanceSnapshot", {"accountId": account_ids[0]}),
            ("/fill/ldeps", {"masterids": account_ids[:3]}),
            ("/order/ldeps", {"masterids": account_ids[:3]}),
            ("/position/ldeps", {"masterids": account_ids[:3]}),
            ("/cashBalance/ldeps", {"masterids": account_ids[:3]}),
            ("/cashBalanceLog/ldeps", {"masterids": account_ids[:3]}),
        ]
        
        for ep, body in post_endpoints:
            result = api_get(base_url, ep, token, 
                           {"masterids": ",".join(str(i) for i in body["masterids"])} if "masterids" in body 
                           else body)
            if isinstance(result, list):
                status = f"{len(result)} items"
                if result:
                    print(f"    ✅ {ep} → {status}")
                    print(f"       Sample: {json.dumps(result[0])[:150]}")
                else:
                    print(f"    ⬚ {ep} → 0 items")
            elif isinstance(result, dict) and "_error" not in result:
                print(f"    ✅ {ep} → {json.dumps(result)[:150]}")
            else:
                err = result.get("_error", "") if isinstance(result, dict) else str(result)
                print(f"    ❌ {ep} → {err}")
        
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")
