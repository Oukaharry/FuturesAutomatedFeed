"""Deeper TopStep exploration - longer waits, GraphQL introspection, billing/account page scraping."""
import json, requests, websocket, time

tabs = requests.get("http://127.0.0.1:9222/json").json()
topstep_tab = next(t for t in tabs if t.get("type") == "page" and "topstep" in t.get("url", "").lower() and "login" not in t.get("url", "").lower())
ws = websocket.create_connection(topstep_tab["webSocketDebuggerUrl"], timeout=60)
msg_id = 1

def cdp(method, params=None):
    global msg_id
    payload = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(payload))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            msg_id += 1
            return resp

def js(expr):
    r = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    result = r.get("result", {}).get("result", {})
    return result.get("value", result.get("description", str(result)))

def api_fetch(label, url, method="GET", body=None):
    print(f"\n=== {label} ===")
    if body:
        body_json = json.dumps(body).replace("\\", "\\\\").replace("'", "\\'").replace("`", "\\`")
        result = js(f"""
            (async () => {{
                const resp = await fetch('{url}', {{
                    method: '{method}',
                    credentials: 'include',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: '{body_json}'
                }});
                const text = await resp.text();
                return resp.status + ' | ' + text.substring(0, 5000);
            }})()
        """)
    else:
        result = js(f"""
            (async () => {{
                const resp = await fetch('{url}', {{
                    credentials: 'include'
                }});
                const text = await resp.text();
                return resp.status + ' | ' + text.substring(0, 5000);
            }})()
        """)
    print(result)

# 1) Profile (already works)
api_fetch("PROFILE", "https://api.topstep.com/me/profile/")

# 2) Accounts basic (0 accounts because this is on the "new" dashboard variant)
api_fetch("ACCOUNTS BASIC", "https://api.topstep.com/me/accounts/basic?offset=0&limit=50&sortBy=createdAt&sortOrder=desc")

# 3) Payouts
api_fetch("PAYOUTS", "https://api.topstep.com/me/payouts/")

# 4) GraphQL introspection - get the schema
api_fetch("GRAPHQL INTROSPECTION", "https://crystal.topstep.com/graphql/introspection", "POST", {
    "query": "{ __schema { queryType { name } mutationType { name } types { name kind fields { name type { name kind ofType { name } } } } } }"
})

# 5) Try GraphQL queries that might exist
api_fetch("GQL - accounts", "https://crystal.topstep.com/graphql/accounts", "POST", {
    "query": "{ me { accounts { id status accountType balance profitTarget } } }"
})

api_fetch("GQL - profile", "https://crystal.topstep.com/graphql/profile", "POST", {
    "query": "{ me { id email firstName lastName } }"
})

# 6) Navigate to accounts and wait longer
print("\n=== NAVIGATING TO ACCOUNTS PAGE ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/accounts'")
time.sleep(5)

print(f"URL: {js('window.location.href')}")
page_text = js("(document.body.innerText || '').substring(0, 5000)")
print(f"\n=== ACCOUNTS PAGE TEXT ===")
print(page_text if page_text else "(empty)")

# Check network after accounts page load
print("\n=== NETWORK AFTER ACCOUNTS PAGE ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (e.name.includes('api.topstep.com') || e.name.includes('crystal.topstep.com'));
    });
    const seen = new Set();
    return apis.filter(e => {
        const u = new URL(e.name);
        const key = u.origin + u.pathname;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
"""))

# 7) Navigate to billing and wait
print("\n=== NAVIGATING TO BILLING PAGE ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/profile/billing'")
time.sleep(5)

page_text = js("(document.body.innerText || '').substring(0, 5000)")
print(f"\n=== BILLING PAGE TEXT ===")
print(page_text if page_text else "(empty)")

# Check network after billing load
print("\n=== NETWORK AFTER BILLING PAGE ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (e.name.includes('api.topstep.com') || e.name.includes('crystal.topstep.com'));
    });
    const seen = new Set();
    return apis.filter(e => {
        const u = new URL(e.name);
        const key = u.origin + u.pathname;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
"""))

# 8) Try more REST endpoint guesses
api_fetch("COMBINES", "https://api.topstep.com/me/combines/")
api_fetch("TRADING ACCOUNTS", "https://api.topstep.com/me/trading-accounts/")
api_fetch("FUNDED ACCOUNTS", "https://api.topstep.com/me/funded-accounts/")
api_fetch("PURCHASE HISTORY", "https://api.topstep.com/me/purchases/")
api_fetch("PAYMENT METHODS", "https://api.topstep.com/me/payment-methods/")

# Navigate back
js("window.location.href = 'https://dashboard.topstep.com/dashboard/default?variant=new'")

ws.close()
print("\nDone.")
