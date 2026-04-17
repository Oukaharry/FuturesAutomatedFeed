"""Find MFFU payout API + stats API + remaining endpoints."""
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

# 1) Enable network interception to see ALL requests during navigation
cdp("Network.enable")

# Navigate to payouts - use client-side routing  
print("=== NAVIGATING TO PAYOUTS (CSR) ===")
js("""
(() => {
    const link = Array.from(document.querySelectorAll('a')).find(a => a.href.includes('/payouts'));
    if (link) link.click();
    return link ? link.href : 'no link found';
})()
""")
time.sleep(3)

# Collect network requests
collected = []
while True:
    try:
        ws.settimeout(0.5)
        resp = json.loads(ws.recv())
        if resp.get("method") == "Network.requestWillBeSent":
            params = resp.get("params", {})
            req = params.get("request", {})
            url = req.get("url", "")
            method = req.get("method", "")
            if "api.myfundedfutures.com" in url or "fundedcms" in url or "_next/data" in url:
                body = req.get("postData", "")
                collected.append(f"[{method}] {url}" + (f" BODY: {body[:200]}" if body else ""))
    except:
        break

ws.settimeout(30)
print("Intercepted requests:")
for r in collected:
    print(f"  {r}")

# Check performance entries again after payouts page
print("\n=== PERFORMANCE ENTRIES ON PAYOUTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (url.includes('api.myfundedfutures.com') || url.includes('_next/data'));
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

# Try common payout API patterns
api_get("PAYOUTS (GET)", "https://api.myfundedfutures.com/api/payouts/")
api_post("PAYOUTS (POST)", "https://api.myfundedfutures.com/api/payouts/")
api_get("USER PAYOUTS", "https://api.myfundedfutures.com/api/user-payouts/")
api_post("USER PAYOUTS (POST)", "https://api.myfundedfutures.com/api/user-payouts/")
api_get("GET PAYOUTS", "https://api.myfundedfutures.com/api/getPayouts/")
api_post("GET PAYOUTS (POST)", "https://api.myfundedfutures.com/api/getPayouts/")
api_get("PAYOUT REQUESTS", "https://api.myfundedfutures.com/api/payout-requests/")
api_post("PAYOUT REQUESTS (POST)", "https://api.myfundedfutures.com/api/payout-requests/")
api_get("WITHDRAWALS", "https://api.myfundedfutures.com/api/withdrawals/")
api_get("USER WITHDRAWALS", "https://api.myfundedfutures.com/api/user-withdrawals/")
api_post("WITHDRAWALS (POST)", "https://api.myfundedfutures.com/api/getWithdrawals/")

# Also try stats endpoint
api_get("STATS", "https://api.myfundedfutures.com/api/user-stats/")
api_get("ACCOUNT STATS", "https://api.myfundedfutures.com/api/account-stats/")
api_get("LEADERBOARD", "https://api.myfundedfutures.com/api/leaderboard/")

# Check Next.js source for API routes
print("\n=== NEXT.JS BUILD MANIFEST ===")
print(js("""
(async () => {
    const buildId = window.__NEXT_DATA__?.buildId || '';
    if (!buildId) return 'No build ID';
    const resp = await fetch('/_next/static/' + buildId + '/_buildManifest.js');
    const text = await resp.text();
    return text.substring(0, 3000);
})()
"""))

# Check page source for API endpoint definitions
print("\n=== PAGE SCRIPTS WITH API REFS ===")
print(js("""
(() => {
    const scripts = Array.from(document.querySelectorAll('script[src]'));
    return scripts.map(s => s.src).filter(s => s.includes('_next')).join('\\n');
})()
"""))

ws.close()
print("\nDone.")
