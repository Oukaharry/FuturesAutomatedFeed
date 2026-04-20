"""
TopStepX API Explorer - Login via Selenium, probe APIs via CDP fetch().
Discovers REST + WebSocket endpoints used by the TopStepX trading platform.
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

# ── Launch Chrome with remote debugging ──
print("Launching Chrome...")
chrome_options = Options()
unique_hash = hashlib.md5(f"topstepx_explore2".encode()).hexdigest()[:8]
user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_topstepx_explore2_{unique_hash}")
chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
chrome_options.add_argument("--remote-debugging-port=9555")
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

def install_interceptors():
    """Install fetch/XHR/WebSocket interceptors in the current page."""
    driver.execute_script("""
        window.__captured = window.__captured || [];
        window.__ws_urls = window.__ws_urls || [];
        
        if (!window.__fetch_hooked) {
            const origFetch = window.fetch;
            window.fetch = function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
                const method = args[1]?.method || 'GET';
                window.__captured.push({type: 'fetch', method, url, time: Date.now()});
                return origFetch.apply(this, args);
            };
            
            const origOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                window.__captured.push({type: 'xhr', method, url: String(url), time: Date.now()});
                return origOpen.apply(this, [method, url, ...rest]);
            };
            
            const origWS = window.WebSocket;
            window.WebSocket = function(url, protocols) {
                window.__ws_urls.push({url: String(url), time: Date.now()});
                window.__captured.push({type: 'ws', method: 'CONNECT', url: String(url), time: Date.now()});
                return protocols ? new origWS(url, protocols) : new origWS(url);
            };
            window.WebSocket.prototype = origWS.prototype;
            window.WebSocket.CONNECTING = origWS.CONNECTING;
            window.WebSocket.OPEN = origWS.OPEN;
            window.WebSocket.CLOSING = origWS.CLOSING;
            window.WebSocket.CLOSED = origWS.CLOSED;
            
            window.__fetch_hooked = true;
        }
    """)

# ── Login ──
print(f"Logging in as {USERNAME}...")
driver.get(LOGIN_URL)
time.sleep(3)
install_interceptors()

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
print("Waiting for login...")

for i in range(20):
    time.sleep(1)
    url = driver.current_url
    if "/login" not in url and "topstepx.com" in url:
        print(f"Logged in! URL: {url}")
        break
else:
    print(f"May not have logged in. URL: {driver.current_url}")

# Re-install interceptors after navigation
time.sleep(3)
install_interceptors()
time.sleep(5)

# ═══════════════════════════════════════════════════════════
# PHASE 1: Dump all captured network requests
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 1: CAPTURED NETWORK REQUESTS (login + initial load)")
print("="*70)

captured = driver.execute_script("return JSON.stringify(window.__captured || [])")
try:
    reqs = json.loads(captured)
    seen = set()
    for r in reqs:
        key = f"{r.get('method','?')} {r.get('url','')}"
        if key not in seen:
            seen.add(key)
            print(f"  [{r['type']:5}] {r.get('method','?'):6} {r['url']}")
    print(f"\nTotal unique requests: {len(seen)}")
except:
    print(captured[:5000])

ws_urls = driver.execute_script("return JSON.stringify(window.__ws_urls || [])")
try:
    ws_list = json.loads(ws_urls)
    if ws_list:
        print(f"\nWebSocket connections ({len(ws_list)}):")
        for w in ws_list:
            print(f"  {w['url']}")
except:
    pass

# ═══════════════════════════════════════════════════════════
# PHASE 2: Storage & Auth tokens
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 2: STORAGE & AUTH TOKENS")
print("="*70)

def probe(label, js_code):
    print(f"\n--- {label} ---")
    try:
        result = driver.execute_script(f"return {js_code}")
        if isinstance(result, str):
            try:
                obj = json.loads(result)
                print(json.dumps(obj, indent=2)[:5000])
            except:
                print(result[:5000])
        else:
            print(json.dumps(result, indent=2)[:5000] if result else "(null)")
    except Exception as e:
        print(f"  ERROR: {e}")

probe("LOCAL STORAGE (all keys)", """
    (() => {
        const result = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            const v = localStorage.getItem(k);
            result[k] = v && v.length > 300 ? v.substring(0, 300) + '...' : v;
        }
        return JSON.stringify(result);
    })()
""")

probe("SESSION STORAGE (all keys)", """
    (() => {
        const result = {};
        for (let i = 0; i < sessionStorage.length; i++) {
            const k = sessionStorage.key(i);
            const v = sessionStorage.getItem(k);
            result[k] = v && v.length > 300 ? v.substring(0, 300) + '...' : v;
        }
        return JSON.stringify(result);
    })()
""")

probe("COOKIES", """
    JSON.stringify(document.cookie.split(';').map(c => c.trim()).filter(c => c.length > 0))
""")

# ═══════════════════════════════════════════════════════════
# PHASE 3: Performance API - all API requests
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 3: PERFORMANCE API - ALL API REQUESTS")
print("="*70)

probe("API CALLS FROM PERFORMANCE", """
    (() => {
        const entries = performance.getEntriesByType('resource');
        const apis = entries.filter(e => 
            e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch' ||
            e.name.includes('/api/') || e.name.includes('graphql') || 
            e.name.includes('.json') || e.name.includes('/v1/') || e.name.includes('/v2/') ||
            e.name.includes('/hub') || e.name.includes('signalr')
        );
        return JSON.stringify(apis.map(e => ({type: e.initiatorType, url: e.name})));
    })()
""")

probe("ALL NETWORK DOMAINS", """
    (() => {
        const entries = performance.getEntriesByType('resource');
        const domains = {};
        entries.forEach(e => {
            try {
                const u = new URL(e.name);
                const key = u.origin;
                if (!domains[key]) domains[key] = {count: 0, paths: []};
                domains[key].count++;
                if (domains[key].paths.length < 8) domains[key].paths.push(u.pathname);
            } catch(err) {}
        });
        return JSON.stringify(domains);
    })()
""")

# ═══════════════════════════════════════════════════════════
# PHASE 4: Probe discovered API base URLs
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 4: PROBING DISCOVERED API ENDPOINTS")
print("="*70)

# First discover API base URLs from captured requests
api_bases = driver.execute_script("""
    return (() => {
        const entries = performance.getEntriesByType('resource');
        const captured = window.__captured || [];
        const allUrls = [
            ...entries.map(e => e.name),
            ...captured.map(c => c.url)
        ];
        const bases = new Set();
        allUrls.forEach(url => {
            try {
                const u = new URL(url);
                if (u.origin !== window.location.origin && !u.origin.includes('google') && 
                    !u.origin.includes('cdn') && !u.origin.includes('static') &&
                    !u.origin.includes('analytics') && !u.origin.includes('sentry')) {
                    bases.add(u.origin);
                }
            } catch(e) {}
        });
        return Array.from(bases);
    })()
""")

print(f"Discovered API base URLs: {api_bases}")

# For each discovered base, try common endpoints
for base in (api_bases or []):
    print(f"\n>>> Probing {base}...")
    endpoints = [
        "/api/me", "/api/profile", "/api/user", "/api/accounts",
        "/api/v1/me", "/api/v1/accounts", "/api/v1/user",
        "/api/positions", "/api/orders", "/api/trades",
        "/api/v1/positions", "/api/v1/orders", "/api/v1/trades",
        "/api/stats", "/api/balance", "/api/symbols",
        "/api/auth/session", "/api/session",
        "/v1/me", "/v1/accounts", "/v1/user",
        "/me", "/accounts", "/user", "/profile",
    ]
    
    for ep in endpoints:
        url = f"{base}{ep}"
        result = driver.execute_script(f"""
            return (async () => {{
                try {{
                    const resp = await fetch('{url}', {{ credentials: 'include' }});
                    const ct = resp.headers.get('content-type') || '';
                    if (resp.status === 404 || resp.status === 405) return JSON.stringify({{status: resp.status}});
                    let body;
                    if (ct.includes('json')) {{
                        body = await resp.json();
                    }} else {{
                        body = (await resp.text()).substring(0, 300);
                    }}
                    return JSON.stringify({{status: resp.status, ct: ct, data: body}}).substring(0, 4000);
                }} catch(e) {{
                    return JSON.stringify({{error: e.message}});
                }}
            }})()
        """)
        try:
            obj = json.loads(result)
            status = obj.get('status', '?')
            if status not in [404, 405, '?'] and 'error' not in obj:
                data = obj.get('data', '')
                preview = json.dumps(data)[:300] if isinstance(data, (dict, list)) else str(data)[:300]
                print(f"  [{status}] {ep}  =>  {preview}")
        except:
            pass

# Also try topstepx.com itself
print(f"\n>>> Probing {BASE_URL}...")
tsx_endpoints = [
    "/api/me", "/api/profile", "/api/user", "/api/accounts",
    "/api/v1/me", "/api/v1/accounts", "/api/positions", "/api/orders",
    "/api/trades", "/api/stats", "/api/balance", "/api/symbols",
    "/api/auth/session", "/api/session", "/api/auth/refresh",
    "/api/v1/positions", "/api/v1/orders", "/api/v1/trades",
    "/api/v1/stats", "/api/v1/balance", "/api/v1/symbols",
    "/api/v1/instruments", "/api/v1/contracts",
    "/api/equity", "/api/drawdown", "/api/performance",
]

for ep in tsx_endpoints:
    url = f"{BASE_URL}{ep}"
    result = driver.execute_script(f"""
        return (async () => {{
            try {{
                const resp = await fetch('{url}', {{ credentials: 'include' }});
                const ct = resp.headers.get('content-type') || '';
                if (resp.status === 404 || resp.status === 405) return JSON.stringify({{status: resp.status}});
                let body;
                if (ct.includes('json')) {{
                    body = await resp.json();
                }} else {{
                    body = (await resp.text()).substring(0, 300);
                }}
                return JSON.stringify({{status: resp.status, ct: ct, data: body}}).substring(0, 4000);
            }} catch(e) {{
                return JSON.stringify({{error: e.message}});
            }}
        }})()
    """)
    try:
        obj = json.loads(result)
        status = obj.get('status', '?')
        if status not in [404, 405, '?'] and 'error' not in obj:
            data = obj.get('data', '')
            preview = json.dumps(data)[:300] if isinstance(data, (dict, list)) else str(data)[:300]
            print(f"  [{status}] {ep}  =>  {preview}")
    except:
        pass

# ═══════════════════════════════════════════════════════════
# PHASE 5: Framework & App State
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 5: FRAMEWORK & APP STATE")
print("="*70)

probe("FRAMEWORK DETECTION", """
    (() => {
        const checks = [];
        if (window.__NEXT_DATA__) checks.push('Next.js: ' + JSON.stringify(window.__NEXT_DATA__).substring(0, 300));
        if (window.__NUXT__) checks.push('Nuxt.js');
        if (window.React || document.querySelector('[data-reactroot]')) checks.push('React');
        if (window.Vue || document.querySelector('[data-v-]')) checks.push('Vue');
        if (window.ng || document.querySelector('[ng-version]')) checks.push('Angular');
        if (window.__remixContext) checks.push('Remix');
        if (window.__APOLLO_CLIENT__) checks.push('Apollo GraphQL');
        if (window.__REDUX_DEVTOOLS_EXTENSION__) checks.push('Redux DevTools');
        
        const globals = Object.keys(window).filter(k => 
            k.startsWith('__') || k.toLowerCase().includes('config') || 
            k.toLowerCase().includes('api') || k.toLowerCase().includes('env') ||
            k.toLowerCase().includes('hub') || k.toLowerCase().includes('signal')
        ).slice(0, 40);
        
        return JSON.stringify({frameworks: checks, relevantGlobals: globals});
    })()
""")

probe("SIGNALR / HUB DETECTION", """
    (() => {
        const results = {};
        // Check for SignalR connections
        const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
        results.scripts = scripts.filter(s => s.includes('signalr') || s.includes('hub'));
        
        // Check performance entries for hub/signalr
        const entries = performance.getEntriesByType('resource');
        results.hubRequests = entries.filter(e => 
            e.name.includes('hub') || e.name.includes('signalr') || e.name.includes('negotiate')
        ).map(e => e.name);
        
        return JSON.stringify(results);
    })()
""")

# ═══════════════════════════════════════════════════════════
# PHASE 6: Page state
# ═══════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  PHASE 6: CURRENT PAGE STATE")
print("="*70)

probe("URL & TITLE", "JSON.stringify({url: window.location.href, title: document.title})")
probe("PAGE TEXT", "(document.body.innerText || '').substring(0, 3000)")

print("\n\nExploration complete. Chrome window remains open for manual inspection.")
print("Close it manually or press Enter to quit.")

try:
    input("\nPress Enter to quit and close Chrome...")
except KeyboardInterrupt:
    pass

driver.quit()
print("Done.")
