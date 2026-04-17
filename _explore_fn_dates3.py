"""
Focused test: Get real account dates from FundedNext.
The account-overview API returned demo data - try intercepting the actual
network calls the metrics page makes, and also try the correct API params.
"""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

port = 9549
opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
driver = webdriver.Chrome(options=opts)

account_id = 3227488
login = 945576089

# Get token
token_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var c = document.cookie.split(';').find(function(c) {
            return c.trim().indexOf('tokenV1=') === 0;
        });
        c ? decodeURIComponent(c.split('=')[1]) : null;
    """,
    "returnByValue": True,
    "timeout": 5000
})
token = token_result.get("result", {}).get("value")

# 1. Try account-overview with the actual login
print("=== ACCOUNT OVERVIEW with login=945576089 ===")
result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": f"""
        (async function() {{
            var resp = await fetch('https://api.fundednext.com/api/v1/account-overview?login={login}', {{
                headers: {{ 'Authorization': 'Bearer {token}', 'Accept': 'application/json' }}
            }});
            return await resp.text();
        }})()
    """,
    "returnByValue": True,
    "awaitPromise": True,
    "timeout": 10000
})
raw = result.get("result", {}).get("value", "{}")
data = json.loads(raw)
# Check if the trading_cycle_details has our real dates
tcd = data.get("data", {}).get("trading_cycle_details", {})
print(f"trading_cycle_details: {json.dumps(tcd, indent=2)}")
acct = data.get("data", {}).get("account_details", {})
print(f"account_details login: {acct.get('login')}")
print(f"account_details type: {acct.get('type')}")

# 2. Enable CDP network interception and navigate to account-metrics page
print("\n\n=== INTERCEPTING NETWORK ON METRICS PAGE ===")
driver.execute_cdp_cmd("Network.enable", {})

# Set up request interception to log API calls
captured = []
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        window._interceptedRequests = [];
        var origFetch = window.fetch;
        window.fetch = function() {
            var url = arguments[0];
            if (typeof url === 'string' && url.includes('api')) {
                window._interceptedRequests.push(url);
            }
            return origFetch.apply(this, arguments);
        };
        var origXHR = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            if (url && url.includes('api')) {
                window._interceptedRequests.push(url);
            }
            return origXHR.apply(this, arguments);
        };
        'interceptors set';
    """,
    "returnByValue": True,
    "timeout": 5000
})

# Navigate to metrics page
print(f"Navigating to account-metrics/{account_id}...")
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": f"window.location.href = 'https://app.fundednext.com/account-metrics/{account_id}'",
    "returnByValue": True,
    "timeout": 5000
})
time.sleep(6)

# Check page content
page_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "document.body.innerText",
    "returnByValue": True,
    "timeout": 5000
})
page_text = page_result.get("result", {}).get("value", "")
print(f"\nMetrics page text ({len(page_text)} chars):")
# Show all lines
for line in page_text.split('\n'):
    if line.strip():
        print(f"  {line.strip()[:150]}")

# Check intercepted requests
int_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "JSON.stringify(window._interceptedRequests || [])",
    "returnByValue": True,
    "timeout": 5000
})
intercepted = json.loads(int_result.get("result", {}).get("value", "[]"))
print(f"\nIntercepted API calls ({len(intercepted)}):")
for url in intercepted:
    print(f"  {url}")

# 3. Try grabbing all React fiber data from metrics page
print("\n\n=== ALL FIBER PROPS WITH DATES ON METRICS PAGE ===")
fiber_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        (function() {
            var body = document.getElementById('__next') || document.body;
            var keys = Object.keys(body);
            for (var j = 0; j < keys.length; j++) {
                if (keys[j].indexOf('__reactFiber') !== -1) {
                    var node = body[keys[j]];
                    var results = [];
                    var visited = new Set();
                    function walk(n, depth) {
                        if (!n || depth > 50 || visited.has(n)) return;
                        visited.add(n);
                        var p = n.memoizedProps;
                        if (p) {
                            var pkeys = Object.keys(p);
                            for (var i = 0; i < pkeys.length; i++) {
                                var v = p[pkeys[i]];
                                if (v && typeof v === 'object' && !Array.isArray(v)) {
                                    var vk = Object.keys(v);
                                    if (vk.some(function(k) { return /start|end|created_at|breach|date/i.test(k); })) {
                                        try {
                                            results.push({key: pkeys[i], depth: depth, data: JSON.parse(JSON.stringify(v))});
                                        } catch(e) {}
                                    }
                                }
                            }
                        }
                        if (n.child) walk(n.child, depth + 1);
                        if (n.sibling) walk(n.sibling, depth + 1);
                    }
                    walk(node, 0);
                    return JSON.stringify(results, null, 2);
                }
            }
            return '[]';
        })()
    """,
    "returnByValue": True,
    "timeout": 15000
})
fraw = fiber_result.get("result", {}).get("value", "[]")
fdata = json.loads(fraw)
print(f"Found {len(fdata)} fiber nodes with date-like fields")
for item in fdata[:10]:
    print(f"\n  key={item.get('key')}, depth={item.get('depth')}")
    d = item.get('data', {})
    for k, v in sorted(d.items()):
        s = str(v)
        if len(s) > 200: s = s[:200] + '...'
        print(f"    {k}: {s}")

print("\nDone!")
