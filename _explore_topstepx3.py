"""
TopStepX API Explorer v3 - Call every discovered userapi.topstepx.com endpoint
and dump full JSON responses. Uses Selenium login to get JWT, then direct fetch().
"""
import json, time, sys, os, hashlib, tempfile
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

USERNAME = "livemoreabundantlyllc@gmail.com"
PASSWORD = "FTn4t4fx6Mna"
BASE_URL = "https://www.topstepx.com"
LOGIN_URL = f"{BASE_URL}/login"
USER_API = "https://userapi.topstepx.com"
CHART_API = "https://chartapi.topstepx.com"

# Known account/user IDs from exploration v2
USER_ID = "342449"
ACCOUNT_ID = "11751547"

# All endpoints discovered in v2
ENDPOINTS = [
    # userapi.topstepx.com
    (USER_API, "/TradingRule", "GET"),
    (USER_API, "/TradingAccount", "GET"),
    (USER_API, "/AccountTemplate/userTemplates", "GET"),
    (USER_API, "/Layouts", "GET"),
    (USER_API, f"/AccountTemplateRule/rules/1/all", "GET"),
    (USER_API, "/UserContract/active/nonprofesional", "GET"),
    (USER_API, "/custom-sounds/list", "GET"),
    (USER_API, "/MarketStatus/markets", "GET"),
    (USER_API, f"/RiskSettingsLockout/active/{ACCOUNT_ID}", "GET"),
    (USER_API, "/UserNotification", "GET"),
    (USER_API, "/Metadata", "GET"),
    (USER_API, f"/LinkedOrder?tradingAccountId={ACCOUNT_ID}", "GET"),
    (USER_API, f"/Trade/id/{ACCOUNT_ID}", "GET"),
    (USER_API, f"/Order?accountId={ACCOUNT_ID}", "GET"),
    (USER_API, f"/Position/all/user/{USER_ID}", "GET"),
    (USER_API, "/brackets", "GET"),
    (USER_API, f"/Violations/active/{ACCOUNT_ID}", "GET"),
    (USER_API, f"/Tilt/activate/{ACCOUNT_ID}?refreshCount=0", "GET"),
    (USER_API, "/charts/all", "GET"),
    # chartapi.topstepx.com
    (CHART_API, "/Config", "GET"),
    # Additional endpoints to probe on userapi
    (USER_API, "/Auth/loginByToken", "GET"),
    (USER_API, "/Auth/me", "GET"),
    (USER_API, "/User", "GET"),
    (USER_API, f"/User/{USER_ID}", "GET"),
    (USER_API, "/TradingAccount/all", "GET"),
    (USER_API, f"/TradingAccount/{ACCOUNT_ID}", "GET"),
    (USER_API, f"/TradingAccount/user/{USER_ID}", "GET"),
    (USER_API, "/Contract", "GET"),
    (USER_API, "/Contract/all", "GET"),
    (USER_API, "/Instrument", "GET"),
    (USER_API, "/Instrument/all", "GET"),
    (USER_API, "/Symbol", "GET"),
    (USER_API, "/Symbol/all", "GET"),
    (USER_API, "/MarketData", "GET"),
    (USER_API, "/AccountBalance", "GET"),
    (USER_API, f"/AccountBalance/{ACCOUNT_ID}", "GET"),
    (USER_API, "/DailyStats", "GET"),
    (USER_API, f"/DailyStats/{ACCOUNT_ID}", "GET"),
    (USER_API, "/TradeHistory", "GET"),
    (USER_API, f"/TradeHistory/{ACCOUNT_ID}", "GET"),
    (USER_API, f"/Trade/all/{ACCOUNT_ID}", "GET"),
    (USER_API, f"/Trade/history/{ACCOUNT_ID}", "GET"),
    (USER_API, "/RiskSettings", "GET"),
    (USER_API, f"/RiskSettings/{ACCOUNT_ID}", "GET"),
    (USER_API, "/Performance", "GET"),
    (USER_API, f"/Performance/{ACCOUNT_ID}", "GET"),
    (USER_API, "/Drawdown", "GET"),
    (USER_API, f"/Drawdown/{ACCOUNT_ID}", "GET"),
    (USER_API, "/Equity", "GET"),
    (USER_API, f"/Equity/{ACCOUNT_ID}", "GET"),
    (USER_API, "/UserSettings", "GET"),
    (USER_API, "/AccountStats", "GET"),
    (USER_API, f"/AccountStats/{ACCOUNT_ID}", "GET"),
    (USER_API, "/Subscription", "GET"),
    (USER_API, f"/Subscription/user/{USER_ID}", "GET"),
    (USER_API, "/Challenge", "GET"),
    (USER_API, f"/Challenge/user/{USER_ID}", "GET"),
    (USER_API, f"/Challenge/{ACCOUNT_ID}", "GET"),
]

# ── Launch Chrome ──
print("Launching Chrome...")
chrome_options = Options()
unique_hash = hashlib.md5(f"topstepx_explore3".encode()).hexdigest()[:8]
user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_topstepx_explore3_{unique_hash}")
chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
chrome_options.add_argument("--remote-debugging-port=9556")
chrome_options.add_argument("--window-size=1400,900")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--no-first-run")
chrome_options.add_argument("--no-default-browser-check")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
chrome_options.add_experimental_option('useAutomationExtension', False)
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=chrome_options)
driver.set_page_load_timeout(30)
driver.implicitly_wait(3)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

# Install interceptors to capture token
driver.execute_script("""
    window.__captured = [];
    window.__ws_urls = [];
    const origOpen = XMLHttpRequest.prototype.open;
    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    const origSend = XMLHttpRequest.prototype.send;
    
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__url = String(url);
        this.__method = method;
        this.__headers = {};
        return origOpen.apply(this, [method, url, ...rest]);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        this.__headers[name] = value;
        return origSetHeader.apply(this, [name, value]);
    };
    XMLHttpRequest.prototype.send = function(body) {
        window.__captured.push({
            type: 'xhr', method: this.__method, url: this.__url,
            headers: this.__headers, time: Date.now()
        });
        return origSend.apply(this, [body]);
    };
    
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        const opts = args[1] || {};
        window.__captured.push({
            type: 'fetch', method: opts.method || 'GET', url,
            headers: opts.headers || {}, time: Date.now()
        });
        return origFetch.apply(this, args);
    };
    
    const origWS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        window.__ws_urls.push(String(url));
        return protocols ? new origWS(url, protocols) : new origWS(url);
    };
    window.WebSocket.prototype = origWS.prototype;
    window.WebSocket.CONNECTING = origWS.CONNECTING;
    window.WebSocket.OPEN = origWS.OPEN;
    window.WebSocket.CLOSING = origWS.CLOSING;
    window.WebSocket.CLOSED = origWS.CLOSED;
""")

# ── Login ──
print(f"Logging in as {USERNAME}...")
driver.get(LOGIN_URL)
time.sleep(3)

wait = WebDriverWait(driver, 15)
username_field = wait.until(EC.presence_of_element_located((By.NAME, "userName")))
username_field.send_keys(Keys.CONTROL + "a")
time.sleep(0.2)
username_field.send_keys(USERNAME)

password_field = driver.find_element(By.NAME, "password")
password_field.send_keys(Keys.CONTROL + "a")
time.sleep(0.2)
password_field.send_keys(PASSWORD)

login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
login_button.click()
print("Waiting for login redirect...")

for i in range(20):
    time.sleep(1)
    url = driver.current_url
    if "/login" not in url and "topstepx.com" in url:
        print(f"Logged in! URL: {url}")
        break
else:
    print(f"May not have logged in. URL: {driver.current_url}")

# Wait for API calls to fire
time.sleep(8)

# ── Extract JWT token ──
print("\n" + "="*70)
print("  EXTRACTING JWT TOKEN")
print("="*70)

token = None

# Method 1: From WebSocket URLs
ws_urls = driver.execute_script("return window.__ws_urls || []")
for ws_url in ws_urls:
    if "access_token=" in ws_url:
        token = ws_url.split("access_token=")[1].split("&")[0]
        print(f"Got token from WebSocket URL (length={len(token)})")
        break

# Method 2: From XHR Authorization headers
if not token:
    captured = driver.execute_script("return JSON.stringify(window.__captured || [])")
    try:
        reqs = json.loads(captured)
        for r in reqs:
            headers = r.get("headers", {})
            auth = headers.get("Authorization", "") or headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth.replace("Bearer ", "")
                print(f"Got token from XHR header (length={len(token)})")
                break
    except:
        pass

# Method 3: Check localStorage / sessionStorage
if not token:
    for storage in ["localStorage", "sessionStorage"]:
        keys = driver.execute_script(f"""
            const keys = [];
            for (let i = 0; i < {storage}.length; i++) keys.push({storage}.key(i));
            return keys;
        """)
        for key in (keys or []):
            val = driver.execute_script(f"return {storage}.getItem('{key}')")
            if val and "eyJ" in str(val):
                # Looks like a JWT
                if "." in val and len(val) > 100:
                    token = val
                    print(f"Got token from {storage}['{key}'] (length={len(token)})")
                    break
                # Maybe JSON containing a token
                try:
                    obj = json.loads(val)
                    for v in (obj.values() if isinstance(obj, dict) else []):
                        if isinstance(v, str) and v.startswith("eyJ") and "." in v:
                            token = v
                            print(f"Got token from {storage}['{key}'] JSON field (length={len(token)})")
                            break
                except:
                    pass
            if token:
                break
        if token:
            break

if not token:
    print("WARNING: Could not extract JWT token!")
    print("Attempting to read from cookie or page context...")
    # Last resort: try to get it from the app's state
    token = driver.execute_script("""
        // Try common patterns
        if (window.__AUTH_TOKEN__) return window.__AUTH_TOKEN__;
        if (window.authToken) return window.authToken;
        if (window.token) return window.token;
        // Check Redux store
        try {
            const state = window.__REDUX_STORE__?.getState?.();
            if (state?.auth?.token) return state.auth.token;
        } catch(e) {}
        return null;
    """)
    if token:
        print(f"Got token from window globals (length={len(token)})")

if token:
    # Decode JWT payload
    import base64
    parts = token.split(".")
    if len(parts) >= 2:
        payload = parts[1]
        # Add padding
        payload += "=" * (4 - len(payload) % 4)
        try:
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            print(f"\nJWT Claims:")
            for k, v in decoded.items():
                print(f"  {k}: {v}")
        except Exception as e:
            print(f"  (Could not decode: {e})")
else:
    print("\nFATAL: No token found. Cannot proceed with API calls.")
    driver.quit()
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
# Call each endpoint using fetch() from the browser context
# (this avoids CORS issues since we're in the page context)
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  CALLING ALL DISCOVERED ENDPOINTS")
print("="*70)

output_file = "_topstepx_api_dump.json"
all_results = {}

for base, path, method in ENDPOINTS:
    url = f"{base}{path}"
    label = f"{base.replace('https://','')}{path}"
    
    result_json = driver.execute_script(f"""
        return (async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: '{method}',
                    headers: {{
                        'Authorization': 'Bearer {token}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    }},
                    credentials: 'include'
                }});
                const status = resp.status;
                const ct = resp.headers.get('content-type') || '';
                let body;
                if (ct.includes('json')) {{
                    body = await resp.json();
                }} else {{
                    const txt = await resp.text();
                    body = txt.substring(0, 500);
                }}
                return JSON.stringify({{status, contentType: ct, data: body}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message}});
            }}
        }})()
    """)
    
    try:
        obj = json.loads(result_json)
        status = obj.get("status", "?")
        error = obj.get("error")
        
        if error:
            print(f"  ERR  {label}  =>  {error}")
            continue
            
        if status in [404, 405, 403, 500, 502, 503]:
            print(f"  [{status}] {label}")
            continue
        
        data = obj.get("data", "")
        ct = obj.get("contentType", "")
        
        # Skip HTML responses (SPA fallback)
        if isinstance(data, str) and "<!doctype" in data.lower():
            print(f"  [{status}] {label}  =>  (HTML - SPA fallback)")
            continue
        
        # Real API response!
        preview = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        truncated = preview[:600]
        if len(preview) > 600:
            truncated += f"\n  ... ({len(preview)} chars total)"
        
        print(f"\n  [{status}] {label}")
        for line in truncated.split("\n"):
            print(f"    {line}")
        
        all_results[label] = {"status": status, "data": data}
        
    except Exception as e:
        print(f"  PARSE_ERR  {label}  =>  {e}")

# ═══════════════════════════════════════════════════════════
# Also try the login/auth endpoint to understand auth flow
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PROBING AUTH ENDPOINTS")
print("="*70)

auth_endpoints = [
    (USER_API, "/Auth/login", "POST", json.dumps({"userName": USERNAME, "password": PASSWORD})),
    (USER_API, "/Auth/loginByToken", "POST", json.dumps({"token": token})),
    (USER_API, "/Auth/refresh", "POST", json.dumps({"token": token})),
    (USER_API, "/Auth/refreshToken", "POST", json.dumps({"token": token})),
    (USER_API, "/Auth/validate", "POST", json.dumps({"token": token})),
    (USER_API, "/Auth/me", "GET", None),
    (USER_API, "/Auth/session", "GET", None),
]

for base, path, method, body in auth_endpoints:
    url = f"{base}{path}"
    label = f"{base.replace('https://','')}{path}"
    
    if body:
        escaped_body = body.replace("'", "\\'").replace("\n", "")
        js = f"""
            return (async () => {{
                try {{
                    const resp = await fetch('{url}', {{
                        method: '{method}',
                        headers: {{
                            'Authorization': 'Bearer {token}',
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        }},
                        body: '{escaped_body}',
                        credentials: 'include'
                    }});
                    const status = resp.status;
                    const ct = resp.headers.get('content-type') || '';
                    let data;
                    if (ct.includes('json')) {{
                        data = await resp.json();
                    }} else {{
                        data = (await resp.text()).substring(0, 500);
                    }}
                    return JSON.stringify({{status, contentType: ct, data}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.message}});
                }}
            }})()
        """
    else:
        js = f"""
            return (async () => {{
                try {{
                    const resp = await fetch('{url}', {{
                        method: '{method}',
                        headers: {{
                            'Authorization': 'Bearer {token}',
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        }},
                        credentials: 'include'
                    }});
                    const status = resp.status;
                    const ct = resp.headers.get('content-type') || '';
                    let data;
                    if (ct.includes('json')) {{
                        data = await resp.json();
                    }} else {{
                        data = (await resp.text()).substring(0, 500);
                    }}
                    return JSON.stringify({{status, contentType: ct, data}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.message}});
                }}
            }})()
        """
    
    result_json = driver.execute_script(js)
    try:
        obj = json.loads(result_json)
        status = obj.get("status", "?")
        error = obj.get("error")
        if error:
            print(f"  ERR  {label}  =>  {error}")
            continue
        data = obj.get("data", "")
        if isinstance(data, str) and "<!doctype" in data.lower():
            print(f"  [{status}] {label}  =>  (HTML)")
            continue
        preview = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        truncated = preview[:800]
        print(f"\n  [{status}] {label}")
        for line in truncated.split("\n"):
            print(f"    {line}")
        all_results[label] = {"status": status, "data": data}
    except Exception as e:
        print(f"  PARSE_ERR  {label}  =>  {e}")

# ═══════════════════════════════════════════════════════════
# Save all results
# ═══════════════════════════════════════════════════════════
print(f"\n\nSaving {len(all_results)} API responses to {output_file}...")
with open(output_file, "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"Saved!")

print(f"\nTotal endpoints with real data: {len(all_results)}")
print("\nChrome window remains open. Press Enter to quit.")

try:
    input()
except KeyboardInterrupt:
    pass

driver.quit()
print("Done.")
