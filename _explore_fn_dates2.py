"""
Deep-dive into promising FundedNext API endpoints for date fields.
"""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

port = 9549
opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
driver = webdriver.Chrome(options=opts)

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

account_id = 3227488
login = 945576089

# 1. Full account-overview response
print("=== ACCOUNT OVERVIEW API (FULL) ===")
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
print(json.dumps(data, indent=2)[:5000])

# 2. Trading overview with type parameter
print("\n\n=== TRADING OVERVIEW API ===")
for ttype in ["demo", "live", "futures", "tradovate", "futures_demo"]:
    result = driver.execute_cdp_cmd("Runtime.evaluate", {
        "expression": f"""
            (async function() {{
                var resp = await fetch('https://api.fundednext.com/api/v1/trading-overview?login={login}&type={ttype}', {{
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
    status = data.get("message", "?")
    body = json.dumps(data)[:300]
    print(f"  type={ttype}: [{status}] {body}")

# 3. Navigate to account-metrics page and extract data
print("\n\n=== ACCOUNT METRICS PAGE ===")
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": f"window.location.href = 'https://app.fundednext.com/account-metrics/{account_id}'",
    "returnByValue": True,
    "timeout": 5000
})
time.sleep(5)

# Get page text
page_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "document.body.innerText",
    "returnByValue": True,
    "timeout": 5000
})
page_text = page_result.get("result", {}).get("value", "")
print(f"Full page text ({len(page_text)} chars):")
print(page_text[:3000])

# Look for date-related content
print("\n\n=== DATE-RELATED LINES ===")
for line in page_text.split('\n'):
    line_lower = line.lower().strip()
    if line_lower and any(w in line_lower for w in ['date', 'start', 'end', 'began', 'created', 'expire', 'day', 'period', 'time', 'duration', 'remaining', '2025', '2026', '/', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']):
        print(f"  -> {line.strip()[:120]}")

# 4. Try to get fiber data from the metrics page
print("\n\n=== METRICS PAGE FIBER ===")
fiber_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        (function() {
            // Try all elements to find React fiber with account/metrics data
            var all = document.querySelectorAll('div, section, main');
            var found = [];
            var checked = new Set();
            for (var i = 0; i < all.length && found.length < 5; i++) {
                var keys = Object.keys(all[i]);
                for (var j = 0; j < keys.length; j++) {
                    if (keys[j].indexOf('__reactFiber') !== -1) {
                        var node = all[i][keys[j]];
                        for (var k = 0; k < 20 && node; k++) {
                            var p = node.memoizedProps;
                            if (p) {
                                var pkeys = Object.keys(p);
                                for (var m = 0; m < pkeys.length; m++) {
                                    var val = p[pkeys[m]];
                                    if (val && typeof val === 'object' && !Array.isArray(val)) {
                                        var vkeys = Object.keys(val);
                                        // Look for objects with date-like keys
                                        var hasDate = vkeys.some(function(k) {
                                            return k.match(/date|start|end|created|time|period|expire/i);
                                        });
                                        var hasAccount = vkeys.some(function(k) {
                                            return k.match(/login|account|balance|breach/i);
                                        });
                                        if ((hasDate || hasAccount) && !checked.has(pkeys[m])) {
                                            checked.add(pkeys[m]);
                                            try {
                                                found.push({
                                                    propKey: pkeys[m],
                                                    keys: vkeys.join(', '),
                                                    data: JSON.parse(JSON.stringify(val))
                                                });
                                            } catch(e) {
                                                found.push({propKey: pkeys[m], keys: vkeys.join(', '), error: e.toString()});
                                            }
                                        }
                                    }
                                }
                            }
                            node = node.return;
                        }
                        break;
                    }
                }
            }
            return JSON.stringify(found, null, 2);
        })()
    """,
    "returnByValue": True,
    "timeout": 15000
})
fraw = fiber_result.get("result", {}).get("value", "[]")
print(fraw[:5000])

print("\nDone!")
