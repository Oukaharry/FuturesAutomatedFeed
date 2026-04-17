"""Use decoded Bearer token (no credentials:include to avoid CORS preflight)."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# Get the decoded token from cookie
token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")
if token:
    print(f"Token: {token[:60]}...")
else:
    # Try localStorage
    token = driver.execute_script("return localStorage.getItem('token') || localStorage.getItem('access_token')")
    print(f"localStorage token: {token[:60] if token else 'None'}...")

base = "https://api.fundednext.com/api/v1"

endpoints = [
    "/plan-wise-ids",
    "/customer/get-profile",
    "/account/self-eligibility-check",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=&page=1&limit=100",
    "/pending-payment-history?email=harryodhiambo17@gmail.com&type=2&account_id=&page=1&limit=100",
    "/customer/accounts",
    "/customer/trading-accounts",
]

for ep in endpoints:
    url = f"{base}{ep}"
    # No credentials:include, use token in Authorization header
    result = driver.execute_script("""
        const url = arguments[0];
        const token = arguments[1];
        try {
            const resp = await fetch(url, {
                method: 'GET',
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
    
    if not result:
        print(f"\n  {ep}: no result")
        continue
    if result.get('error'):
        print(f"\n  {ep}: {result['error']}")
        continue
    status = result.get('status', 0)
    body = result.get('body', '')
    print(f"\n{'='*60}")
    print(f"{ep}  [HTTP {status}]")
    
    if status in (404, 405, 500):
        continue
    
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")
                    for item in v[:3]:
                        if isinstance(item, dict):
                            print(f"    {json.dumps(item, indent=4, default=str)[:1500]}")
                        else:
                            print(f"    {item}")
                elif isinstance(v, dict):
                    print(f"  {k}: {json.dumps(v, indent=2, default=str)[:1000]}")
                else:
                    print(f"  {k}: {str(v)[:300]}")
        elif isinstance(data, list):
            print(f"  Array[{len(data)}]")
            for item in data[:3]:
                print(f"  {json.dumps(item, indent=2, default=str)[:500]}")
    except:
        print(f"  Raw: {body[:500]}")

# Also try: intercept the XHR the page already makes
print("\n\n=== Intercepting page's own API calls ===")
# Navigate to billing page to trigger API calls and intercept them
result = driver.execute_script("""
    // Monkey-patch XHR to capture responses
    window._fnApiCaptures = [];
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._fnUrl = url;
        this._fnMethod = method;
        return origOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            if (this._fnUrl && this._fnUrl.includes('api.fundednext.com')) {
                window._fnApiCaptures.push({
                    url: this._fnUrl,
                    status: this.status,
                    body: this.responseText.substring(0, 5000)
                });
            }
        });
        return origSend.call(this, ...args);
    };
    return 'interceptor installed';
""")
print(f"Interceptor: {result}")

# Navigate to billing page
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)

# Collect intercepted calls
captures = driver.execute_script("return window._fnApiCaptures || [];")
print(f"\nIntercepted {len(captures)} API calls:")
for cap in captures:
    url = cap.get('url', '')
    status = cap.get('status', 0)
    body = cap.get('body', '')
    
    # Skip tracking/analytics
    if any(x in url for x in ['analytics', 'pixel', 'google', 'clarity', 'tiktok']):
        continue
    
    print(f"\n{'='*60}")
    print(f"URL: {url}")
    print(f"Status: {status}")
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")
                    for item in v[:2]:
                        if isinstance(item, dict):
                            print(f"    {json.dumps(item, indent=4, default=str)[:1500]}")
                        else:
                            print(f"    {item}")
                elif isinstance(v, dict):
                    print(f"  {k}: {json.dumps(v, indent=2, default=str)[:800]}")
                else:
                    print(f"  {k}: {str(v)[:300]}")
    except:
        print(f"  Raw: {body[:300]}")

# Now navigate to accounts and intercept those calls
print("\n\n=== Now navigating to accounts page ===")
driver.execute_script("window._fnApiCaptures = [];")
driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

captures2 = driver.execute_script("return window._fnApiCaptures || [];")
print(f"\nIntercepted {len(captures2)} API calls from accounts page:")
for cap in captures2:
    url = cap.get('url', '')
    status = cap.get('status', 0)
    body = cap.get('body', '')
    if any(x in url for x in ['analytics', 'pixel', 'google', 'clarity', 'tiktok', 'reddit', 'lrkt']):
        continue
    print(f"\n{'='*60}")
    print(f"URL: {url}")
    print(f"Status: {status}")
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")
                    for item in v[:2]:
                        if isinstance(item, dict):
                            print(f"    {json.dumps(item, indent=4, default=str)[:2000]}")
                        else:
                            print(f"    {item}")
                elif isinstance(v, dict):
                    print(f"  {k}: {json.dumps(v, indent=2, default=str)[:1000]}")
                else:
                    print(f"  {k}: {str(v)[:300]}")
    except:
        print(f"  Raw: {body[:500]}")

print("\n\nDONE")
