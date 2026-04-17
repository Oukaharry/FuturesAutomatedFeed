"""Use browser's credential context to call FundedNext APIs with cookies."""
import time, json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# First navigate to the FundedNext domain so cookies are sent automatically
if "fundednext.com" not in driver.current_url:
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(3)

# Get the decoded token
token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")
print(f"Decoded token: {token[:80] if token else 'None'}...")

base = "https://api.fundednext.com/api/v1"

endpoints = [
    "/plan-wise-ids",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=&page=1&limit=100",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=2&account_id=&page=1&limit=100",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=3&account_id=&page=1&limit=100",
    "/customer/get-profile",
    "/account/self-eligibility-check",
    "/customer/accounts",
    "/customer/trading-accounts",
    "/accounts",
    "/trading-accounts",
    "/customer/all-accounts",
    "/customer/plans",
    "/order/list",
    "/order/history",
    "/payment/history",
    "/billing/history",
    "/billing/list",
]

for ep in endpoints:
    url = f"{base}{ep}"
    # Use fetch with credentials:include to send cookies, plus the decoded Bearer token
    result = driver.execute_script("""
        const url = arguments[0];
        const token = arguments[1];
        try {
            const resp = await fetch(url, {
                credentials: 'include',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json'
                }
            });
            const text = await resp.text();
            return {status: resp.status, body: text.substring(0, 5000)};
        } catch(e) {
            return {error: e.toString()};
        }
    """, url, token)
    
    if not result or result.get('error'):
        print(f"\n  {ep}: ERROR - {result.get('error', 'unknown')}")
        continue
    status = result.get('status', 0)
    if status in (404, 405, 500):
        continue
    
    body = result.get('body', '')
    print(f"\n{'='*60}")
    print(f"ENDPOINT: {ep}  (status {status})")
    
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")
                    for item in v[:3]:
                        if isinstance(item, dict):
                            print(f"    keys: {list(item.keys())}")
                            print(f"    {json.dumps(item, indent=4, default=str)[:1200]}")
                        else:
                            print(f"    {item}")
                elif isinstance(v, dict):
                    print(f"  {k}: {json.dumps(v, indent=2, default=str)[:800]}")
                else:
                    print(f"  {k}: {str(v)[:200]}")
        elif isinstance(data, list):
            print(f"  Array[{len(data)}]")
            for item in data[:3]:
                print(f"  {json.dumps(item, indent=2, default=str)[:500]}")
    except:
        print(f"  Raw: {body[:500]}")

print("\n\nDONE")
