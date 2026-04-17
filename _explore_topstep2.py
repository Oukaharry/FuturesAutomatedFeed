"""Call TopStep APIs via CDP fetch() calls."""
import json, requests, websocket, time

tabs = requests.get("http://127.0.0.1:9222/json").json()
topstep_tab = next(t for t in tabs if t.get("type") == "page" and "topstep" in t.get("url", "").lower() and "login" not in t.get("url", "").lower())
ws = websocket.create_connection(topstep_tab["webSocketDebuggerUrl"], timeout=30)
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

def api_call(label, url):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const resp = await fetch('{url}', {{
                credentials: 'include'
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 4000);
        }})()
    """)
    print(result)

def graphql_call(label, query, variables=None):
    print(f"\n=== {label} ===")
    payload = json.dumps({"query": query, "variables": variables or {}}).replace("'", "\\'").replace("`", "\\`")
    result = js(f"""
        (async () => {{
            const resp = await fetch('https://crystal.topstep.com/graphql/{label.replace(' ','').replace('/','_')}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{ 'Content-Type': 'application/json' }},
                body: '{payload}'
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 4000);
        }})()
    """)
    print(result)

# REST API calls discovered from network
api_call("PROFILE", "https://api.topstep.com/me/profile/")
api_call("ACCOUNTS BASIC", "https://api.topstep.com/me/accounts/basic?offset=0&limit=15&sortBy=createdAt&sortOrder=desc")
api_call("REFRESH TOKEN", "https://api.topstep.com/auth/refresh-token")

# Try additional REST endpoints
api_call("ACCOUNTS", "https://api.topstep.com/me/accounts/")
api_call("ACCOUNTS DETAIL", "https://api.topstep.com/me/accounts/detail?offset=0&limit=15")
api_call("PAYOUTS", "https://api.topstep.com/me/payouts/")
api_call("ORDERS", "https://api.topstep.com/me/orders/")
api_call("BILLING", "https://api.topstep.com/me/billing/")
api_call("SUBSCRIPTIONS", "https://api.topstep.com/me/subscriptions/")
api_call("TRANSACTIONS", "https://api.topstep.com/me/transactions/")
api_call("INVOICES", "https://api.topstep.com/me/invoices/")

# GraphQL - try TopstepTV live status (discovered endpoint)
graphql_call("TopstepTVLiveStatus", "{ topstepTVLiveStatus { isLive streamUrl } }")

# Navigate to accounts page to discover more endpoints
print("\n=== NAVIGATING TO ACCOUNTS PAGE ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/accounts'")
time.sleep(3)

print(f"URL: {js('window.location.href')}")

# Get page text
print("\n=== ACCOUNTS PAGE TEXT ===")
print(js("(document.body.innerText || '').substring(0, 4000)"))

# Check new network requests 
print("\n=== NEW API REQUESTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (url.includes('api.topstep.com') || url.includes('crystal.topstep.com') || url.includes('graphql'));
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

# Navigate to billing page
print("\n=== NAVIGATING TO BILLING PAGE ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/profile/billing'")
time.sleep(3)

print(f"URL: {js('window.location.href')}")

print("\n=== BILLING PAGE TEXT ===")
print(js("(document.body.innerText || '').substring(0, 4000)"))

# Check billing API requests
print("\n=== BILLING API REQUESTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (url.includes('api.topstep.com') || url.includes('crystal.topstep.com') || url.includes('graphql'));
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

# Navigate to payouts page 
print("\n=== NAVIGATING TO PAYOUTS PAGE ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/payouts'")
time.sleep(3)

print(f"URL: {js('window.location.href')}")

print("\n=== PAYOUTS PAGE TEXT ===")
print(js("(document.body.innerText || '').substring(0, 4000)"))

# Final network request summary
print("\n=== ALL UNIQUE API REQUESTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (url.includes('api.topstep.com') || url.includes('crystal.topstep.com'));
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

# Navigate back to default dashboard
js("window.location.href = 'https://dashboard.topstep.com/dashboard/default?variant=new'")

ws.close()
print("\nDone.")
