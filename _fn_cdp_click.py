"""Use CDP Runtime.evaluate to bypass Selenium's page load wait."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)
d.set_page_load_timeout(15)
d.set_script_timeout(10)

# First recover to accounts page
try:
    d.get("https://app.fundednext.com/accounts")
except:
    pass
time.sleep(4)

# Use CDP to read body
result = d.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "document.body.innerText.substring(0, 500)",
    "returnByValue": True,
    "timeout": 5000
})
body = result.get("result", {}).get("value", "")
print(f"Body:\n{body[:300]}", flush=True)

# Click Futures via CDP
d.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        (function() {
            var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
            for (var i = 0; i < tabs.length; i++) {
                if (tabs[i].textContent.trim() === 'Futures') {
                    tabs[i].click();
                    return 'clicked';
                }
            }
            return 'not found';
        })()
    """,
    "returnByValue": True
})
print("Clicked Futures via CDP", flush=True)

time.sleep(6)

# Read via CDP (doesn't wait for page load)
result2 = d.execute_cdp_cmd("Runtime.evaluate", {
    "expression": "document.body.innerText.substring(0, 2000)",
    "returnByValue": True,
    "timeout": 5000
})
body2 = result2.get("result", {}).get("value", "")
has_error = "Something Went Wrong" in body2
has_fnft = "FNFT" in body2
print(f"\nAfter Futures: error={has_error}, FNFT={has_fnft}", flush=True)
print(f"Text:\n{body2[:1000]}", flush=True)

if has_fnft:
    # Get card data
    result3 = d.execute_cdp_cmd("Runtime.evaluate", {
        "expression": """
            (function() {
                var cards = document.querySelectorAll('.dashboard-card');
                return Array.from(cards).map(function(c) { return c.textContent.substring(0, 500); });
            })()
        """,
        "returnByValue": True
    })
    cards = result3.get("result", {}).get("value", [])
    print(f"\nCards: {json.dumps(cards, indent=2)}", flush=True)
    
    # Try to get full account data from fiber
    result4 = d.execute_cdp_cmd("Runtime.evaluate", {
        "expression": """
            (function() {
                var cards = document.querySelectorAll('.dashboard-card');
                var results = [];
                for (var i = 0; i < cards.length; i++) {
                    var keys = Object.keys(cards[i]);
                    for (var j = 0; j < keys.length; j++) {
                        if (keys[j].indexOf('__reactFiber') !== -1) {
                            var node = cards[i][keys[j]];
                            for (var k = 0; k < 30 && node; k++) {
                                var p = node.memoizedProps;
                                if (p) {
                                    try {
                                        var s = JSON.stringify(p);
                                        if (s.indexOf('login') !== -1 || s.indexOf('account_id') !== -1 || s.indexOf('945576089') !== -1) {
                                            results.push(s.substring(0, 5000));
                                            break;
                                        }
                                    } catch(e) {}
                                }
                                node = node.return;
                            }
                        }
                    }
                }
                return results;
            })()
        """,
        "returnByValue": True
    })
    fiber = result4.get("result", {}).get("value", [])
    print(f"\nFiber with login/account data: {len(fiber)}", flush=True)
    for fd in fiber:
        try:
            data = json.loads(fd)
            print(json.dumps(data, indent=2)[:3000], flush=True)
        except:
            print(fd[:2000], flush=True)
    
    # Also try: look for any element containing 945576089
    result5 = d.execute_cdp_cmd("Runtime.evaluate", {
        "expression": "document.body.innerHTML.indexOf('945576089') !== -1",
        "returnByValue": True
    })
    print(f"\n945576089 in page HTML: {result5.get('result', {}).get('value')}", flush=True)

elif has_error:
    # Page crashed - let's check the error
    result_err = d.execute_cdp_cmd("Runtime.evaluate", {
        "expression": """
            (function() {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    if (all[i].textContent.indexOf('Something Went Wrong') !== -1 && all[i].children.length < 3) {
                        return all[i].outerHTML.substring(0, 1000);
                    }
                }
                return 'error element not found';
            })()
        """,
        "returnByValue": True
    })
    print(f"Error element: {result_err.get('result', {}).get('value', '')[:500]}", flush=True)
    
    # Get browser console errors
    result_console = d.execute_cdp_cmd("Runtime.evaluate", {
        "expression": "window._consoleErrors ? window._consoleErrors.join('\\n').substring(0, 2000) : 'no captured errors'",
        "returnByValue": True
    })
    print(f"Console errors: {result_console.get('result', {}).get('value', '')[:500]}", flush=True)

# Clean up by navigating away
d.execute_cdp_cmd("Page.navigate", {"url": "https://app.fundednext.com/accounts"})

print("\nDONE", flush=True)
