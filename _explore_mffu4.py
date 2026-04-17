"""Explore MFFU API - POST endpoints, accounts, payouts, intercept XHR."""
import sys, io, json, requests, websocket, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

tabs = requests.get("http://127.0.0.1:9222/json").json()
mffu_tab = next(t for t in tabs if t.get("type") == "page" and "myfundedfutures" in t.get("url", "").lower())
ws = websocket.create_connection(mffu_tab["webSocketDebuggerUrl"], timeout=30)
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

def api_post(label, url, body="{}"):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const resp = await fetch('{url}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{'Content-Type': 'application/json'}},
                body: '{body}'
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.replace(/[\\u200b]/g, '').substring(0, 8000);
        }})()
    """)
    print(result)

def api_get(label, url):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const resp = await fetch('{url}', {{ credentials: 'include' }});
            const text = await resp.text();
            return resp.status + ' | ' + text.replace(/[\\u200b]/g, '').substring(0, 8000);
        }})()
    """)
    print(result)

# 1) Accounts list - discovered endpoint from navigation
api_get("ACCOUNTS LIST (all statuses)", "https://api.myfundedfutures.com/api/user-prop-accounts/?page=1&page_size=100")
api_get("ACCOUNT CATEGORIES", "https://api.myfundedfutures.com/api/user-prop-account-categories/")

# 2) Try POST for subscriptions and receipts
api_post("SUBSCRIPTIONS (POST)", "https://api.myfundedfutures.com/api/getSubscriptions/")
api_post("RECEIPTS (POST)", "https://api.myfundedfutures.com/api/getReceipts/")
api_post("CERTIFICATES (POST)", "https://api.myfundedfutures.com/api/getCertificates/")

# 3) Navigate to payouts to discover API
print("\n=== FINDING PAYOUT API ===")
# Install XHR interceptor first
js("""
(() => {
    window.__mffu_requests = [];
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        const opts = args[1] || {};
        window.__mffu_requests.push({
            url, method: opts.method || 'GET',
            body: typeof opts.body === 'string' ? opts.body.substring(0, 500) : null
        });
        return origFetch.apply(this, args);
    };
    const origXHR = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        window.__mffu_requests.push({ url, method, body: null });
        return origXHR.apply(this, arguments);
    };
})()
""")

# Navigate to payouts
js("window.location.href = 'https://myfundedfutures.com/payouts'")
time.sleep(4)

# Check intercepted requests
print(js("""
(() => {
    return JSON.stringify(
        window.__mffu_requests?.filter(r => 
            r.url.includes('api.myfundedfutures.com') || r.url.includes('fundedcms.com')
        ) || [], null, 2
    );
})()
"""))

# Check for __NEXT_DATA__ with payouts API info
print("\n=== NEXT DATA ===")
print(js("""
(() => {
    const nd = window.__NEXT_DATA__;
    if (nd) {
        return JSON.stringify({
            page: nd.page,
            query: nd.query,
            buildId: nd.buildId,
            propsKeys: Object.keys(nd.props || {}),
            pagePropsKeys: Object.keys(nd.props?.pageProps || {})
        }, null, 2);
    }
    return 'No __NEXT_DATA__';
})()
"""))

# Navigate to stats page
print("\n=== NAVIGATING TO STATS ===")
js("window.__mffu_requests = []")
js("window.location.href = 'https://myfundedfutures.com/stats'")
time.sleep(4)

print(js("""
(() => {
    return JSON.stringify(
        window.__mffu_requests?.filter(r => 
            r.url.includes('api.myfundedfutures.com') || r.url.includes('fundedcms.com')
        ) || [], null, 2
    );
})()
"""))

# Stats page content
print("\n=== STATS PAGE TEXT ===")
print(js("(document.body.innerText || '').replace(/[\\u200b]/g, '').substring(0, 3000)"))

# Navigate back to billing
js("window.location.href = 'https://myfundedfutures.com/billing'")

ws.close()
print("\nDone.")
