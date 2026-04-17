"""Explore Lucid Trading APIs via CDP fetch() calls."""
import json, requests, websocket

# Find the Lucid dashboard tab
tabs = requests.get("http://127.0.0.1:9222/json").json()
lucid_tab = None
for t in tabs:
    if t.get("type") == "page" and "dash.lucidtrading.com" in t.get("url", "") and "pdf" not in t.get("url", ""):
        lucid_tab = t
        break

ws_url = lucid_tab["webSocketDebuggerUrl"]
ws = websocket.create_connection(ws_url, timeout=30)
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
    if result.get("type") == "undefined":
        return None
    val = result.get("value", result.get("description", str(result)))
    return val

def api_call(label, url):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const token = localStorage.getItem('auth_token');
            const resp = await fetch('{url}', {{
                headers: {{ 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }}
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 3000);
        }})()
    """)
    print(result)

# Key: userKey = Z9WS86Z9 from localStorage
USER_KEY = "Z9WS86Z9"

# Call discovered API endpoints
api_call("USER SUMMARY", f"https://dash.lucidtrading.com/api/users/summary/{USER_KEY}")
api_call("WP PROFILE", f"https://dash.lucidtrading.com/api/users/wp-profile?userKey={USER_KEY}")
api_call("ACCOUNTS / PLANS", "https://dash.lucidtrading.com/api/accounts/plans")
api_call("CURRENT PROMO", "https://dash.lucidtrading.com/api/users/current-promo")
api_call("CRATE STATUS", "https://dash.lucidtrading.com/api/rewards/crate-status")
api_call("AFFILIATE CHECK", "https://dash.lucidtrading.com/api/affiliate/check")
api_call("AFFILIATE WALLET", "https://dash.lucidtrading.com/api/affiliate/wallet/blocked")
api_call("AFFILIATE ORDERS", "https://dash.lucidtrading.com/api/affiliate/orders/allowed")

# Try additional likely endpoints
api_call("ACCOUNTS LIST", "https://dash.lucidtrading.com/api/accounts")
api_call("ACCOUNT DETAILS", f"https://dash.lucidtrading.com/api/accounts/{USER_KEY}")
api_call("PAYOUTS", "https://dash.lucidtrading.com/api/payouts")
api_call("PAYOUTS BY USER", f"https://dash.lucidtrading.com/api/payouts/{USER_KEY}")
api_call("ORDERS", "https://dash.lucidtrading.com/api/orders")
api_call("BILLING", "https://dash.lucidtrading.com/api/billing")
api_call("TRANSACTIONS", "https://dash.lucidtrading.com/api/transactions")
api_call("USER PROFILE", "https://dash.lucidtrading.com/api/users/profile")
api_call("USER ME", "https://dash.lucidtrading.com/api/users/me")

# Now navigate to account-details page and grab text
print("\n=== NAVIGATING TO ACCOUNT DETAILS PAGE ===")
js("window.location.hash = '#/account-details'")
import time; time.sleep(2)

print("\n=== ACCOUNT DETAILS PAGE TEXT ===")
page_text = js("""
(() => {
    return document.body.innerText.substring(0, 4000);
})()
""")
print(page_text)

# Navigate to payouts page
print("\n=== NAVIGATING TO PAYOUTS PAGE ===")
js("window.location.hash = '#/payouts'")
time.sleep(2)

print("\n=== PAYOUTS PAGE TEXT ===")
page_text = js("""
(() => {
    return document.body.innerText.substring(0, 4000);
})()
""")
print(page_text)

# Grab any new network requests after navigation
print("\n=== NEW NETWORK REQUESTS ===")
net = js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => 
        (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
        e.name.includes('/api/')
    );
    return apis.map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
""")
print(net)

# Navigate back to account summary
js("window.location.hash = '#/account-summary'")

ws.close()
print("\nDone.")
