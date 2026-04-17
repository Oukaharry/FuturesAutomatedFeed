"""
Check individual account pages on FundedNext for date fields.
Also check the API for account-specific endpoints with dates.
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

# 1. Try navigating to account detail page 
print("=== CHECKING ACCOUNT DETAIL PAGES ===")
detail_urls = [
    f"https://app.fundednext.com/accounts/{account_id}",
    f"https://app.fundednext.com/accounts/{login}",
    f"https://app.fundednext.com/account-metrics/{account_id}",
    f"https://app.fundednext.com/account-metrics/{login}",
]

for url in detail_urls:
    print(f"\nTrying: {url}")
    result = driver.execute_cdp_cmd("Runtime.evaluate", {
        "expression": f"""
            (async function() {{
                try {{
                    var resp = await fetch('{url}', {{redirect: 'manual'}});
                    return JSON.stringify({{status: resp.status, type: resp.type, url: resp.url}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.toString()}});
                }}
            }})()
        """,
        "returnByValue": True,
        "awaitPromise": True,
        "timeout": 10000
    })
    print(f"  Result: {result.get('result', {}).get('value', 'N/A')}")

# 2. Try the API for account-specific endpoints
print("\n\n=== CHECKING API ENDPOINTS ===")

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
print(f"Token: {token[:30]}..." if token else "No token!")

api_endpoints = [
    f"https://api.fundednext.com/api/v1/get-account/{account_id}",
    f"https://api.fundednext.com/api/v1/account/{account_id}",
    f"https://api.fundednext.com/api/v1/accounts/{account_id}",
    f"https://api.fundednext.com/api/v1/account-detail/{account_id}",
    f"https://api.fundednext.com/api/v1/dashboard/{account_id}",
    f"https://api.fundednext.com/api/v1/get-account-metrics?account_id={account_id}",
    f"https://api.fundednext.com/api/v1/trading-overview?login={login}",
    f"https://api.fundednext.com/api/v1/account-overview?login={login}",
    f"https://api.fundednext.com/api/v1/get-accounts?type=active&page=1&limit=20",
    f"https://api.fundednext.com/api/v1/get-accounts?type=breached&page=1&limit=20",
    f"https://api.fundednext.com/api/v1/get-accounts?type=all&page=1&limit=20",
]

for url in api_endpoints:
    result = driver.execute_cdp_cmd("Runtime.evaluate", {
        "expression": f"""
            (async function() {{
                try {{
                    var resp = await fetch('{url}', {{
                        headers: {{
                            'Authorization': 'Bearer {token}',
                            'Accept': 'application/json'
                        }}
                    }});
                    var text = await resp.text();
                    return JSON.stringify({{status: resp.status, body: text.substring(0, 500)}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.toString()}});
                }}
            }})()
        """,
        "returnByValue": True,
        "awaitPromise": True,
        "timeout": 10000
    })
    raw = result.get("result", {}).get("value", "{}")
    data = json.loads(raw)
    status = data.get("status", "?")
    body_preview = data.get("body", "")[:200]
    if data.get("error"):
        print(f"  [{status}] {url.split('v1/')[1]}  ERROR: {data['error']}")
    else:
        print(f"  [{status}] {url.split('v1/')[1]}  -> {body_preview}")
    
print("\n\n=== CHECKING ACCOUNT METRICS PAGE VIA NAVIGATION ===")
# Navigate to the account metrics page (FundedNext uses this for individual account stats)
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": f"window.location.href = 'https://app.fundednext.com/account-metrics/{account_id}'",
    "returnByValue": True,
    "timeout": 5000
})
time.sleep(4)

# Check what's on the metrics page
page_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "document.body.innerText.substring(0, 2000)",
    "returnByValue": True,
    "timeout": 5000
})
page_text = page_result.get("result", {}).get("value", "")
print(f"Page text:\n{page_text[:1500]}")

# Check for any date-related text on the page
print("\n=== DATE-RELATED TEXT ===")
for line in page_text.split('\n'):
    line_lower = line.lower()
    if any(w in line_lower for w in ['date', 'start', 'end', 'began', 'created', 'expire', 'day', 'period']):
        print(f"  -> {line.strip()}")

# Also try extracting React fiber on this page
print("\n=== FIBER DATA ON METRICS PAGE ===")
metrics_fiber = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        (function() {
            // Look for main content container with React fiber data
            var els = document.querySelectorAll('[class*=metric], [class*=overview], [class*=card], [class*=stat]');
            var results = [];
            for (var i = 0; i < Math.min(els.length, 10); i++) {
                var keys = Object.keys(els[i]);
                for (var j = 0; j < keys.length; j++) {
                    if (keys[j].indexOf('__reactFiber') !== -1) {
                        var node = els[i][keys[j]];
                        for (var k = 0; k < 30 && node; k++) {
                            var p = node.memoizedProps;
                            if (p && (p.account || p.data || p.metrics || p.overview || p.accountData)) {
                                var target = p.account || p.data || p.metrics || p.overview || p.accountData;
                                try {
                                    results.push({
                                        className: els[i].className.substring(0, 50),
                                        propKey: Object.keys(p).filter(function(k){ return typeof p[k] === 'object' && p[k]; }).join(','),
                                        data: JSON.parse(JSON.stringify(target))
                                    });
                                } catch(e) {
                                    results.push({className: els[i].className.substring(0, 50), error: e.toString()});
                                }
                                break;
                            }
                            node = node.return;
                        }
                        break;
                    }
                }
            }
            return JSON.stringify(results, null, 2);
        })()
    """,
    "returnByValue": True,
    "timeout": 10000
})
fraw = metrics_fiber.get("result", {}).get("value", "[]")
print(fraw[:3000])

print("\nDone!")
