"""Use the auth token from Chrome to call FundedNext backend APIs directly."""
import time, json, re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# Get auth token  
token = None
for c in driver.get_cookies():
    if c['name'] == 'tokenV1':
        token = c['value']
        print(f"Token: {token[:50]}...")
        break

# Get user info from localStorage
user_json = driver.execute_script("return localStorage.getItem('user');")
user = json.loads(user_json) if user_json else {}
print(f"User ID: {user.get('id')}, Name: {user.get('full_name')}")

# Now use the token to call FundedNext APIs
# The site is Next.js (app.fundednext.com) but the actual API is likely at a different domain
# Let's find it by looking at the network requests

# Method: Use CDP to capture ALL network traffic while navigating
print("\n=== Enabling CDP Network monitoring ===")

# Enable network domain
driver.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 10000000})

# Clear and navigate
print("Navigating to billing page...")
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(8)

# Get all network URLs via performance API
urls = driver.execute_script("""
    return performance.getEntriesByType('resource').map(e => ({
        name: e.name, 
        type: e.initiatorType,
        duration: Math.round(e.duration)
    })).filter(e => e.type === 'xmlhttprequest' || e.type === 'fetch' || e.name.includes('api'));
""")

print(f"\nNetwork requests ({len(urls)} XHR/fetch/api):")
for u in urls:
    print(f"  [{u['type']}] {u['name']}")

# Also try fetching known FundedNext API domain patterns
print("\n=== Testing known FundedNext API domains ===")

# FundedNext typically uses these backends:
api_domains = [
    "https://api.fundednext.com",
    "https://app.fundednext.com/api", 
    "https://backend.fundednext.com",
]

for domain in api_domains:
    for endpoint in ["/user/accounts", "/accounts", "/trading-accounts", "/billing/history",
                     "/billing-history", "/user/trading-accounts", "/v1/accounts",
                     "/customer/accounts", "/customer/billing"]:
        url = f"{domain}{endpoint}"
        result = driver.execute_script(f"""
            try {{
                const resp = await fetch('{url}', {{
                    headers: {{
                        'Authorization': 'Bearer {token}',
                        'Accept': 'application/json'
                    }}
                }});
                if (resp.status === 404 || resp.status === 405) return null;
                const text = await resp.text();
                return {{status: resp.status, body: text.substring(0, 2000), url: '{url}'}};
            }} catch(e) {{
                return null;
            }}
        """)
        if result:
            print(f"\n  HIT: {url} (status {result['status']})")
            body = result['body']
            try:
                data = json.loads(body)
                if isinstance(data, dict):
                    print(f"  Keys: {list(data.keys())}")
                    # Print any list of accounts
                    for k in data:
                        v = data[k]
                        if isinstance(v, list) and v:
                            print(f"  {k}[0]: {json.dumps(v[0], indent=2)[:500]}")
                        elif isinstance(v, (str, int, float, bool)):
                            print(f"  {k}: {v}")
                elif isinstance(data, list) and data:
                    print(f"  Array of {len(data)} items")
                    print(f"  [0]: {json.dumps(data[0], indent=2)[:500]}")
            except:
                print(f"  Body: {body[:300]}")

# Now scrape the billing table with React fiber data
print("\n=== Billing table React fiber data ===")

# Navigate to billing if not already there
if "billing" not in driver.current_url:
    driver.get("https://app.fundednext.com/billing/billing-history")
    time.sleep(5)

# Click Futures if present
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        time.sleep(3)
        print("Clicked Futures on billing")
        break
    except:
        pass

# Extract React fiber data from table rows
fiber_data = driver.execute_script("""
    const rows = document.querySelectorAll('.ant-table-wrapper table tbody tr.ant-table-row');
    const results = [];
    for (const row of rows) {
        const fiberKey = Object.keys(row).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (fiberKey) {
            let fiber = row[fiberKey];
            // Walk up to find memoizedProps with record/data
            let depth = 0;
            while (fiber && depth < 10) {
                const props = fiber.memoizedProps || {};
                if (props.record) {
                    results.push(JSON.parse(JSON.stringify(props.record)));
                    break;
                }
                if (props.children && Array.isArray(props.children)) {
                    // Check children for record props
                }
                fiber = fiber.return;
                depth++;
            }
        }
    }
    return results;
""")

print(f"Fiber records found: {len(fiber_data)}")
for i, record in enumerate(fiber_data):
    print(f"\n  Record {i+1}:")
    print(f"  {json.dumps(record, indent=2, default=str)[:800]}")

# Also check the accounts page React data
print("\n=== Accounts page React data ===")
driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

# Click Futures
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        time.sleep(3)
        print("Clicked Futures")
        break
    except:
        pass

# Get React fiber from account cards
card_data = driver.execute_script("""
    const cards = document.querySelectorAll('.dashboard-card');
    const results = [];
    for (const card of cards) {
        const fiberKey = Object.keys(card).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (fiberKey) {
            let fiber = card[fiberKey];
            let depth = 0;
            while (fiber && depth < 20) {
                const props = fiber.memoizedProps || {};
                // Look for account data
                if (props.account || props.data || props.accountData || props.item) {
                    const data = props.account || props.data || props.accountData || props.item;
                    try {
                        results.push({props_keys: Object.keys(props), data: JSON.parse(JSON.stringify(data))});
                    } catch(e) {
                        results.push({keys: Object.keys(props)});
                    }
                    break;
                }
                fiber = fiber.return;
                depth++;
            }
        }
    }
    return results;
""")

print(f"Card React data found: {len(card_data)}")
for i, record in enumerate(card_data):
    print(f"\n  Card {i+1}:")
    print(f"  {json.dumps(record, indent=2, default=str)[:1000]}")

print("\nDONE")
