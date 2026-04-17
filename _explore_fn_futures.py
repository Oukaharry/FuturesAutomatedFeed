"""Click Futures tab, intercept API, get account data."""
import time, json, traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

try:
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
    driver = webdriver.Chrome(options=opts)
    print(f"URL: {driver.current_url}", flush=True)

    # Get token
    token = driver.execute_script("""
        var c = document.cookie.split(';').find(function(c) { return c.trim().indexOf('tokenV1=') === 0; });
        return c ? decodeURIComponent(c.split('=')[1]) : null;
    """)
    print(f"Token: {bool(token)}", flush=True)

    # Navigate to accounts
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(4)
    
    # Install interceptor BEFORE clicking
    driver.execute_script("""
        window._apiCalls = [];
        var origOpen = XMLHttpRequest.prototype.open;
        var origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            return origOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function() {
            var self = this;
            this.addEventListener('load', function() {
                if (self._url && self._url.indexOf('api.fundednext.com') !== -1) {
                    window._apiCalls.push({url: self._url, status: self.status, body: self.responseText.substring(0, 10000)});
                }
            });
            return origSend.apply(this, arguments);
        };
    """)
    print("Interceptor installed", flush=True)

    # Click the Futures tab
    driver.execute_script("""
        var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === 'Futures') {
                tabs[i].click();
                break;
            }
        }
    """)
    print("Clicked Futures tab", flush=True)
    time.sleep(5)

    # Get page text after clicking Futures
    text = driver.execute_script("return document.body.innerText.substring(0, 5000);")
    print(f"\nPage text after Futures click:\n{text[:3000]}", flush=True)
    
    # Check intercepted calls
    captures = driver.execute_script("return window._apiCalls || [];")
    print(f"\nIntercepted {len(captures)} API calls:", flush=True)
    for cap in captures:
        url = cap.get('url', '')
        if any(x in url for x in ['coupon', 'notification', 'alert', 'newsletter', 'survey', 'announcement', 'competition', 'free-trial', 'wrap', 'banner', 'popup', 'eligibility', 'profile']):
            continue
        print(f"\n{'='*50}", flush=True)
        print(f"URL: {url}", flush=True)
        print(f"Status: {cap.get('status')}", flush=True)
        body = cap.get('body', '')
        try:
            data = json.loads(body)
            print(json.dumps(data, indent=2, default=str)[:5000], flush=True)
        except:
            print(f"Raw: {body[:2000]}", flush=True)

    # 2. Also try: direct API call for futures accounts 
    # The XHR interception found the URL pattern, let's also try some variations
    print("\n\n=== DIRECT API CALLS ===", flush=True)
    for ep in [
        "/get-accounts?type=active&page=1&limit=6&platform=futures",
        "/get-accounts?type=active&page=1&limit=6&category=futures",
        "/get-accounts?type=active&page=1&limit=6&plan_type=futures",
        "/get-accounts?type=active&page=1&limit=6&server_type=futures",
        "/get-accounts?type=active&page=1&limit=6&server_type=tradovate", 
        "/get-futures-accounts?type=active&page=1&limit=6",
        "/futures/get-accounts?type=active&page=1&limit=6",
    ]:
        url = f"https://api.fundednext.com/api/v1{ep}"
        result = driver.execute_script("""
            var url = arguments[0];
            var token = arguments[1];
            try {
                var resp = await fetch(url, {
                    headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
                });
                var text = await resp.text();
                return {status: resp.status, body: text.substring(0, 3000)};
            } catch(e) {
                return {error: e.toString()};
            }
        """, url, token)
        if not result or result.get('error'):
            continue
        status = result.get('status', 0)
        if status in (404, 405, 500):
            continue
        body = result.get('body', '')
        try:
            data = json.loads(body)
            total = data.get('data', {}).get('total', 'N/A') if isinstance(data.get('data'), dict) else 'N/A'
            print(f"  {ep} -> HTTP {status}, total: {total}", flush=True)
            if total != 0 and total != 'N/A':
                print(f"    {json.dumps(data, indent=2, default=str)[:3000]}", flush=True)
        except:
            print(f"  {ep} -> HTTP {status}: {body[:200]}", flush=True)

except Exception as e:
    traceback.print_exc()

print("\nDONE", flush=True)
