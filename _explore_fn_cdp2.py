"""Use CDP Network domain to intercept ALL API calls during page navigation."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# Get decoded token
token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")
print(f"Token: {token[:50]}...")

base = "https://api.fundednext.com/api/v1"

# === Part 1: Call billing endpoint correctly ===
print("\n=== BILLING HISTORY (type=1, limit=20) ===")
result = driver.execute_script("""
    const url = arguments[0];
    const token = arguments[1];
    const resp = await fetch(url, {
        headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    });
    return {status: resp.status, body: await resp.text()};
""", f"{base}/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=&page=1&limit=20", token)

if result:
    print(f"Status: {result['status']}")
    try:
        data = json.loads(result['body'])
        if 'data' in data and isinstance(data['data'], list):
            print(f"  Billing rows: {len(data['data'])}")
            for item in data['data'][:5]:
                print(f"\n  {json.dumps(item, indent=4, default=str)}")
        elif 'data' in data and isinstance(data['data'], dict):
            d = data['data']
            if 'data' in d:
                print(f"  Billing rows: {len(d['data'])}")
                for item in d['data'][:5]:
                    print(f"\n  {json.dumps(item, indent=4, default=str)}")
            else:
                print(f"  {json.dumps(d, indent=2, default=str)[:3000]}")
        else:
            print(f"  {json.dumps(data, indent=2, default=str)[:3000]}")
    except:
        print(f"  Raw: {result['body'][:2000]}")

# === Part 2: Use CDP to intercept network during page loads ===
print("\n\n=== CDP NETWORK INTERCEPT: ACCOUNTS PAGE ===")

# Enable CDP network monitoring
driver.execute_cdp_cmd("Network.enable", {})

# Collect response bodies
captured = {}

def on_response(params):
    url = params.get('response', {}).get('url', '')
    if 'api.fundednext.com' in url:
        req_id = params.get('requestId')
        captured[req_id] = url

# Can't use event listeners easily with selenium CDP, so use a different approach:
# Navigate and then use Performance API to get all resources
driver.get("https://app.fundednext.com/accounts")
time.sleep(6)

# Get all performance resource entries
perf_entries = driver.execute_script("""
    return performance.getEntriesByType('resource')
        .filter(e => e.name.includes('api.fundednext.com'))
        .map(e => ({name: e.name, type: e.initiatorType, duration: e.duration}));
""")

print(f"API requests on accounts page: {len(perf_entries)}")
for entry in perf_entries:
    name = entry.get('name', '')
    if any(x in name for x in ['analytics', 'pixel', 'google', 'clarity', 'tiktok', 'reddit', 'lrkt', 'datafa']):
        continue
    print(f"  [{entry.get('type')}] {name[:200]}")

# Now probe each unique API URL we found
unique_urls = set()
for entry in perf_entries:
    name = entry.get('name', '')
    if 'api.fundednext.com' in name and not any(x in name for x in ['analytics', 'pixel', 'google', 'clarity', 'tiktok', 'reddit', 'lrkt', 'datafa']):
        # Get base URL without query params for deduplication
        unique_urls.add(name)

print(f"\n=== Fetching {len(unique_urls)} API responses ===")
for url in sorted(unique_urls):
    if any(skip in url for skip in ['coupon-count', 'unread-count', 'notification', 'dashboard-alert', 'payout-wallet', 'news-alert', 'newsletter', 'survey', 'competition', 'rum']):
        continue
    result = driver.execute_script("""
        const url = arguments[0];
        const token = arguments[1];
        const resp = await fetch(url, {
            headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        });
        return {status: resp.status, body: await resp.text()};
    """, url, token)
    
    if not result or result.get('status', 0) >= 400:
        continue
    
    body = result.get('body', '')
    print(f"\n{'='*60}")
    print(f"URL: {url[:150]}")
    print(f"Status: {result['status']}")
    try:
        data = json.loads(body)
        # Look for anything containing account number, tradovate, FNFT
        body_str = body.lower()
        has_account_info = any(x in body_str for x in ['fnft', 'tradovate', 'trading_account', 'account_number', 'account_name', 'login', 'server'])
        if has_account_info:
            print(f"  *** CONTAINS ACCOUNT INFO ***")
            print(f"  {json.dumps(data, indent=2, default=str)[:3000]}")
        else:
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (list, dict)):
                        sz = len(v) if isinstance(v, list) else len(v.keys())
                        print(f"  {k}: {'list' if isinstance(v, list) else 'dict'}[{sz}]")
                    else:
                        print(f"  {k}: {str(v)[:100]}")
    except:
        print(f"  Raw: {body[:300]}")


# === Part 3: Navigate to billing and intercept ===
print("\n\n=== CDP NETWORK INTERCEPT: BILLING PAGE ===")
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(6)

perf_entries2 = driver.execute_script("""
    return performance.getEntriesByType('resource')
        .filter(e => e.name.includes('api.fundednext.com'))
        .map(e => ({name: e.name, type: e.initiatorType}));
""")

print(f"API requests on billing page: {len(perf_entries2)}")
unique_urls2 = set()
for entry in perf_entries2:
    name = entry.get('name', '')
    if 'api.fundednext.com' in name and not any(x in name for x in ['analytics', 'pixel', 'google', 'clarity', 'tiktok', 'reddit', 'lrkt', 'datafa']):
        unique_urls2.add(name)

for url in sorted(unique_urls2):
    if any(skip in url for skip in ['coupon-count', 'unread-count', 'notification', 'dashboard-alert', 'payout-wallet', 'news-alert', 'newsletter', 'survey', 'competition', 'rum']):
        continue
    # Only fetch URLs we haven't already checked
    if url in unique_urls:
        continue
    
    result = driver.execute_script("""
        const url = arguments[0];
        const token = arguments[1];
        const resp = await fetch(url, {
            headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        });
        return {status: resp.status, body: await resp.text()};
    """, url, token)
    
    if not result or result.get('status', 0) >= 400:
        continue
    print(f"\n{'='*60}")
    print(f"URL: {url[:150]}")
    print(f"Status: {result['status']}")
    body = result.get('body', '')
    try:
        data = json.loads(body)
        print(f"  {json.dumps(data, indent=2, default=str)[:2000]}")
    except:
        print(f"  Raw: {body[:500]}")

# === Part 4: Try some guessed account-related endpoints ===
print("\n\n=== PROBING ACCOUNT ENDPOINTS ===")
account_eps = [
    "/customer/dashboard",
    "/customer/dashboard/accounts",
    "/dashboard/account-list",
    "/dashboard/my-accounts",
    "/my-account",
    "/my-accounts",
    "/account/list",
    "/account/my-list",
    "/account/dashboard",
    "/customer/account",
    "/futures/accounts",
    "/futures/my-accounts",
    "/account/futures",
    "/customer/futures",
]

for ep in account_eps:
    url = f"{base}{ep}"
    result = driver.execute_script("""
        const url = arguments[0];
        const token = arguments[1];
        try {
            const resp = await fetch(url, {
                headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
            });
            return {status: resp.status, body: await resp.text()};
        } catch(e) {
            return {error: e.toString()};
        }
    """, url, token)
    
    if not result or result.get('error') or result.get('status', 0) in (404, 405, 500):
        continue
    print(f"\n  {ep} -> HTTP {result['status']}")
    body = result.get('body', '')[:1000]
    try:
        data = json.loads(body)
        print(f"    {json.dumps(data, indent=2, default=str)[:800]}")
    except:
        print(f"    Raw: {body[:300]}")

driver.execute_cdp_cmd("Network.disable", {})
print("\n\nDONE")
