"""Focused: call the FundedNext API endpoints we found."""
import time, json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# Get token
token = None
for c in driver.get_cookies():
    if c['name'] == 'tokenV1':
        token = c['value']
        break
print(f"Token found: {bool(token)}")

base = "https://api.fundednext.com/api/v1"

# Call specific endpoints we discovered
endpoints = [
    "/plan-wise-ids",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=&page=1&limit=100",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=2&account_id=&page=1&limit=100",
    "/customer/get-profile",
    "/account/self-eligibility-check",
    # Try account listing endpoints
    "/customer/accounts",
    "/customer/trading-accounts",
    "/accounts",
    "/trading-accounts",
    "/customer/all-accounts",
    "/customer/account-list",
    "/customer/futures-accounts",
    "/plan/list",
    "/plan/my-plans",
    "/customer/plans",
    "/customer/orders",
    "/customer/order-history",
    "/order/list",
    "/order/history",
    "/payment/history",
    "/billing/history",
    "/billing/list",
    "/transaction/history",
    "/transaction/list",
]

for ep in endpoints:
    url = f"{base}{ep}"
    result = driver.execute_script(f"""
        try {{
            const resp = await fetch('{url}', {{
                headers: {{
                    'Authorization': 'Bearer {token}',
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }}
            }});
            const text = await resp.text();
            return {{status: resp.status, body: text.substring(0, 3000)}};
        }} catch(e) {{
            return {{error: e.toString()}};
        }}
    """)
    if not result or result.get('error'):
        continue
    status = result.get('status', 0)
    if status in (404, 405, 500, 403):
        continue
    
    body = result.get('body', '')
    print(f"\n{'='*60}")
    print(f"ENDPOINT: {ep}")
    print(f"Status: {status}")
    
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            # Print top-level keys and their types
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list of {len(v)} items")
                    if v:
                        if isinstance(v[0], dict):
                            print(f"    [0] keys: {list(v[0].keys())}")
                            print(f"    [0]: {json.dumps(v[0], indent=4)[:1000]}")
                        else:
                            print(f"    [0]: {v[0]}")
                elif isinstance(v, dict):
                    print(f"  {k}: dict with keys {list(v.keys())}")
                    # Print nested if it looks like account data
                    vstr = json.dumps(v, indent=2)[:500]
                    print(f"    {vstr}")
                else:
                    vstr = str(v)
                    if len(vstr) > 200:
                        vstr = vstr[:200] + "..."
                    print(f"  {k}: {vstr}")
        elif isinstance(data, list):
            print(f"  Array of {len(data)} items")
            if data:
                print(f"  [0]: {json.dumps(data[0], indent=2)[:500]}")
    except:
        print(f"  Raw: {body[:500]}")

print("\n\nDONE")
