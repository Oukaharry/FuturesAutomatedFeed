"""Call MFFU APIs via CDP fetch() calls."""
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

def api_call(label, url):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const resp = await fetch('{url}', {{ credentials: 'include' }});
            const text = await resp.text();
            return resp.status + ' | ' + text.replace(/[\\u200b\\u200c\\u200d\\ufeff]/g, '').substring(0, 6000);
        }})()
    """)
    print(result)

# Discovered API endpoints from network requests
api_call("PROFILE", "https://api.myfundedfutures.com/api/getProfile/")
api_call("SUBSCRIPTIONS", "https://api.myfundedfutures.com/api/getSubscriptions/")
api_call("RECEIPTS", "https://api.myfundedfutures.com/api/getReceipts/")
api_call("PAYMENT METHODS", "https://api.myfundedfutures.com/api/getUserPaymentMethods/")
api_call("SUPPORTED PROCESSORS", "https://api.myfundedfutures.com/api/getSupportedProcessors/")
api_call("SITE ALERTS", "https://api.myfundedfutures.com/api/site-alerts/public/")
api_call("GLOBAL SETTINGS", "https://app.fundedcms.com/api/global-setting?pLevel")

# Try additional likely endpoints based on nav items
api_call("ACCOUNTS", "https://api.myfundedfutures.com/api/getAccounts/")
api_call("PAYOUTS", "https://api.myfundedfutures.com/api/getPayouts/")
api_call("STATS", "https://api.myfundedfutures.com/api/getStats/")
api_call("CERTIFICATES", "https://api.myfundedfutures.com/api/getCertificates/")
api_call("PROMOTIONS", "https://api.myfundedfutures.com/api/getPromotions/")
api_call("AFFILIATES", "https://api.myfundedfutures.com/api/getAffiliates/")
api_call("PLATFORMS", "https://api.myfundedfutures.com/api/getPlatforms/")

# Navigate to accounts page to find more endpoints
print("\n=== NAVIGATING TO ACCOUNTS PAGE ===")
js("window.location.href = 'https://myfundedfutures.com/accounts'")
time.sleep(4)

print(f"URL: {js('window.location.href')}")
page_text = js("(document.body.innerText || '').replace(/[\\u200b]/g,'').substring(0, 5000)")
print(f"\n=== ACCOUNTS PAGE TEXT ===")
print(page_text)

# New API requests from accounts page
print("\n=== NEW API REQUESTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (e.name.includes('api.myfundedfutures.com') || e.name.includes('fundedcms.com'));
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

# Navigate to payouts
print("\n=== NAVIGATING TO PAYOUTS PAGE ===")
js("window.location.href = 'https://myfundedfutures.com/payouts'")
time.sleep(4)

page_text = js("(document.body.innerText || '').replace(/[\\u200b]/g,'').substring(0, 3000)")
print(f"\n=== PAYOUTS PAGE TEXT ===")
print(page_text)

# Final network requests
print("\n=== ALL UNIQUE API REQUESTS ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        return (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
               (e.name.includes('api.myfundedfutures.com') || e.name.includes('fundedcms.com'));
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

# Navigate back to billing
js("window.location.href = 'https://myfundedfutures.com/billing'")

ws.close()
print("\nDone.")
