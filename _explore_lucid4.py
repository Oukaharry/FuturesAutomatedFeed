"""Call the remaining Lucid Trading API endpoints discovered from page navigation."""
import json, requests, websocket

tabs = requests.get("http://127.0.0.1:9222/json").json()
lucid_tab = next(t for t in tabs if t.get("type") == "page" and "dash.lucidtrading.com" in t.get("url", "") and "pdf" not in t.get("url", ""))
ws = websocket.create_connection(lucid_tab["webSocketDebuggerUrl"], timeout=30)
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
            const token = localStorage.getItem('auth_token');
            const resp = await fetch('{url}', {{
                headers: {{ 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }}
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 4000);
        }})()
    """)
    print(result)

USER_KEY = "Z9WS86Z9"
ACCT_KEY = "07ZS9T7C"

# Newly discovered endpoints
api_call("ACCOUNT INFO", f"https://dash.lucidtrading.com/api/users/accountInfo/{USER_KEY}?accountKey={ACCT_KEY}")
api_call("PAYOUT REQUESTS", f"https://dash.lucidtrading.com/api/payout/payout-requests?userKey={USER_KEY}")
api_call("PAYOUT HISTORY", f"https://dash.lucidtrading.com/api/payout/payout-history?userKey={USER_KEY}")
api_call("CRYPTO PAYMENT METHODS", "https://dash.lucidtrading.com/api/payout/confirmo/crypto-payment-methods")
api_call("OTP", "https://dash.lucidtrading.com/api/users/otp")

# Try additional guesses for order/billing info
api_call("ORDERS BY USER KEY", f"https://dash.lucidtrading.com/api/orders/{USER_KEY}")
api_call("WP ORDERS", f"https://dash.lucidtrading.com/api/users/orders?userKey={USER_KEY}")
api_call("WP ORDERS2", f"https://dash.lucidtrading.com/api/orders/history?userKey={USER_KEY}")
api_call("PURCHASES", f"https://dash.lucidtrading.com/api/purchases?userKey={USER_KEY}")
api_call("INVOICES", f"https://dash.lucidtrading.com/api/invoices?userKey={USER_KEY}")
api_call("ACCOUNT HISTORY", f"https://dash.lucidtrading.com/api/accounts/history/{ACCT_KEY}")
api_call("ACCOUNT TRADES", f"https://dash.lucidtrading.com/api/accounts/trades/{ACCT_KEY}")
api_call("RESET HISTORY", f"https://dash.lucidtrading.com/api/accounts/resets/{USER_KEY}")

# Navigate to add-account page to find purchase/billing links
print("\n=== NAVIGATING TO ADD ACCOUNT PAGE ===")
js("window.location.hash = '#/add-account'")
import time; time.sleep(2)
page_text = js("document.body.innerText.substring(0, 3000)")
print(page_text)

# Check performance entries for new endpoints on add-account page
print("\n=== NEW NETWORK REQUESTS FROM ADD-ACCOUNT ===")
net = js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => 
        (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
        e.name.includes('/api/')
    );
    // Deduplicate
    const seen = new Set();
    const unique = apis.filter(e => {
        const url = new URL(e.name).pathname;
        if (seen.has(url)) return false;
        seen.add(url);
        return true;
    });
    return unique.map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
""")
print(net)

# Navigate back
js("window.location.hash = '#/account-summary'")

ws.close()
print("\nDone.")
