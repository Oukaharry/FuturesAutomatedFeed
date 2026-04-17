import json, sys
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import LucidTradingAccount

s = LucidTradingAccount(debug_port=9222)
s.login()

token = s._js("localStorage.getItem('auth_token')")
user_key = s._js("localStorage.getItem('userKey')")
base = "https://dash.lucidtrading.com/api"

# Test more API patterns
endpoints_bearer = [
    f"/account/{user_key}",
    f"/account/{user_key}/summary",
    f"/account-detail/{user_key}",
    f"/prop-accounts/{user_key}",
    f"/orders/{user_key}",
    f"/positions/{user_key}",
    f"/balance/{user_key}",
    "/account",
    "/accounts",
    "/dashboard",
    "/prop-accounts",
    "/orders",
    "/positions",
    f"/user-accounts",
]

print("=== Testing more endpoints with Bearer ===")
for ep in endpoints_bearer:
    url = f"{base}{ep}"
    result = s._fetch_json_bearer(url, token)
    if result:
        txt = json.dumps(result)[:200]
        print(f"  OK  {ep}: {txt}")
    else:
        # Also log the status
        pass

# Now try to extract data from the DOM  
print("\n=== DOM Extraction ===")
dom_data = s._js("""
    (() => {
        // Look for account balance or any meaningful data on the page
        const texts = [];
        // Check table cells
        document.querySelectorAll('td, .balance, .account, .equity, [class*=balance], [class*=account], [class*=equity]').forEach(el => {
            const t = el.textContent.trim();
            if (t && t.length < 100) texts.push(t);
        });
        return JSON.stringify(texts.slice(0, 50));
    })()
""")
print("DOM data elements:", dom_data)

# Check the page title / headings
headings = s._js("""
    (() => {
        const h = [];
        document.querySelectorAll('h1,h2,h3,h4,h5,h6,.title,.header').forEach(el => {
            h.push(el.textContent.trim());
        });
        return JSON.stringify(h.slice(0, 20));
    })()
""")
print("Headings:", headings)

# Try to install a network interceptor and navigate to trigger requests
print("\n=== Installing fetch interceptor ===")
s._js("""
    (() => {
        window.__lucidRequests = [];
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            window.__lucidRequests.push(url);
            return origFetch.apply(this, args);
        };
        
        const origXHR = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            window.__lucidRequests.push(url);
            return origXHR.call(this, method, url, ...rest);
        };
        return 'interceptors installed';
    })()
""")

# Navigate to a page to trigger fresh requests
import time
s._js("window.location.hash = '#/account-summary'")
time.sleep(3)

# Check intercepted requests
requests = s._js("JSON.stringify(window.__lucidRequests || [])")
print("Intercepted requests:", requests)

s.close()
