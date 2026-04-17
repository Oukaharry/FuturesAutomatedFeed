"""
Explore ALL fields available in the React fiber account object on the FundedNext dashboard.
Connects to the already-open Chrome session and dumps the full account object.
"""
import hashlib
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Connect to existing FundedNext Chrome
port = 9549
print(f"Connecting to Chrome debug port: {port}")

opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
driver = webdriver.Chrome(options=opts)

print(f"Current URL: {driver.current_url}")
print(f"Title: {driver.title}")

# Navigate to accounts page if not already there
if "/accounts" not in driver.current_url:
    print("Navigating to accounts page...")
    driver.get("https://app.fundednext.com/accounts")
    import time; time.sleep(3)

# Click Futures tab via CDP
print("\nClicking Futures tab via CDP...")
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === 'Futures') {
                tabs[i].click();
                'clicked Futures';
            }
        }
    """,
    "returnByValue": True,
    "timeout": 5000
})
import time; time.sleep(3)

# Extract ALL fields from React fiber account objects
print("\n=== FULL ACCOUNT OBJECT DUMP ===\n")
result = driver.execute_cdp_cmd("Runtime.evaluate", {
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
                            if (p && p.account && p.account.login) {
                                var acct = p.account;
                                // Get ALL top-level keys and their values
                                var full = {};
                                var acctKeys = Object.keys(acct);
                                for (var m = 0; m < acctKeys.length; m++) {
                                    var val = acct[acctKeys[m]];
                                    if (val !== null && typeof val === 'object') {
                                        // For nested objects, get their keys too
                                        try {
                                            full[acctKeys[m]] = JSON.parse(JSON.stringify(val));
                                        } catch(e) {
                                            full[acctKeys[m]] = String(val);
                                        }
                                    } else {
                                        full[acctKeys[m]] = val;
                                    }
                                }
                                results.push(full);
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

raw = result.get("result", {}).get("value", "[]")
accounts = json.loads(raw)

for i, acct in enumerate(accounts):
    print(f"\n--- Account #{i+1} ---")
    for key in sorted(acct.keys()):
        val = acct[key]
        if isinstance(val, dict):
            print(f"  {key}: {{")
            for sk, sv in sorted(val.items()):
                print(f"    {sk}: {sv}")
            print(f"  }}")
        else:
            print(f"  {key}: {val}")

# Also check if there's a stats/detail page we can access
print("\n\n=== CHECKING ACCOUNT DETAIL LINKS ===")
links_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var links = [];
        var anchors = document.querySelectorAll('a[href*="account"]');
        for (var i = 0; i < anchors.length; i++) {
            links.push({href: anchors[i].href, text: anchors[i].textContent.trim().substring(0, 80)});
        }
        JSON.stringify(links);
    """,
    "returnByValue": True,
    "timeout": 5000
})
links_raw = links_result.get("result", {}).get("value", "[]")
links = json.loads(links_raw)
for l in links:
    print(f"  {l['href']}  ->  {l['text'][:60]}")

print("\nDone!")
