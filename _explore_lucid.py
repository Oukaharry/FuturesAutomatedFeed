"""Explore Lucid Trading dashboard via CDP on port 9222."""
import json, requests, websocket

# Find the Lucid tab
tabs = requests.get("http://127.0.0.1:9222/json").json()
lucid_tab = None
for t in tabs:
    print(f"  [{t.get('type','?')}] {t.get('title','?')[:60]}  url={t.get('url','')[:80]}")
    if "lucid" in t.get("url", "").lower() or "lucid" in t.get("title", "").lower():
        lucid_tab = t

if not lucid_tab:
    print("\nERROR: No Lucid Trading tab found. Available tabs listed above.")
    exit(1)

print(f"\n=== LUCID TAB ===")
print(f"Title: {lucid_tab['title']}")
print(f"URL: {lucid_tab['url']}")
ws_url = lucid_tab["webSocketDebuggerUrl"]

ws = websocket.create_connection(ws_url, timeout=30)
msg_id = 1

def cdp(method, params=None):
    global msg_id
    payload = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(payload))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            msg_id += 1
            return resp
        # skip events

def js(expr, await_promise=False):
    r = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
    result = r.get("result", {}).get("result", {})
    if result.get("type") == "undefined":
        return None
    return result.get("value", result.get("description", str(result)))

# 1) Current URL and page title
print(f"\n=== CURRENT STATE ===")
print(f"URL: {js('window.location.href')}")
print(f"Title: {js('document.title')}")

# 2) Get cookies/domain info
print(f"\n=== COOKIES ===")
cookies = js("document.cookie")
print(cookies[:500] if cookies else "(no accessible cookies - likely httpOnly)")

# 3) Capture network requests by intercepting fetch/XHR
print("\n=== INTERCEPTING NETWORK REQUESTS ===")
# Enable network domain to see requests
cdp("Network.enable")

# 4) Get page structure - nav items, main content areas
print("\n=== NAV / SIDEBAR ===")
nav_text = js("""
(() => {
    // Try common nav selectors
    const selectors = ['nav', '[class*="sidebar"]', '[class*="nav"]', '[class*="menu"]', 
                       '[role="navigation"]', '.sidebar', '#sidebar', '[class*="Sidebar"]'];
    let results = [];
    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            const text = el.innerText.trim().substring(0, 500);
            if (text && text.length > 5) {
                results.push(`[${sel}] ${text}`);
            }
        });
    }
    return results.join('\\n---\\n');
})()
""")
print(nav_text)

# 5) Get all links on the page
print("\n=== ALL LINKS ===")
links = js("""
(() => {
    const links = Array.from(document.querySelectorAll('a[href]'));
    return links.map(a => `${a.href} | ${a.innerText.trim().substring(0, 60)}`).join('\\n');
})()
""")
print(links[:3000] if links else "(no links)")

# 6) Get main content area text
print("\n=== MAIN CONTENT ===")
main_text = js("""
(() => {
    const selectors = ['main', '[class*="content"]', '[class*="dashboard"]', '[role="main"]', '#root', '#app'];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
            const text = el.innerText.trim().substring(0, 3000);
            if (text.length > 20) return `[${sel}] ${text}`;
        }
    }
    return document.body.innerText.trim().substring(0, 3000);
})()
""")
print(main_text)

# 7) Look for account-related data in the DOM
print("\n=== ACCOUNT DATA SEARCH ===")
acct_data = js("""
(() => {
    const body = document.body.innerText;
    const patterns = [
        /account[\\s#:]*\\w+/gi,
        /balance[\\s:$]*[\\d,.]+/gi,
        /\\$[\\d,]+\\.\\d{2}/g,
        /profit[\\s:$]*[\\d,.]+/gi,
        /loss[\\s:$]*[\\d,.]+/gi,
        /drawdown[\\s:$]*[\\d,.]+/gi,
        /funded|evaluation|challenge|breach/gi,
    ];
    let found = [];
    for (const p of patterns) {
        const matches = body.match(p);
        if (matches) found.push(...matches.slice(0, 10));
    }
    return [...new Set(found)].join('\\n');
})()
""")
print(acct_data)

# 8) Check for React/Vue/Angular state
print("\n=== FRAMEWORK DETECTION ===")
framework = js("""
(() => {
    const checks = [];
    if (window.__NEXT_DATA__) checks.push('Next.js: ' + JSON.stringify(window.__NEXT_DATA__).substring(0, 500));
    if (window.__NUXT__) checks.push('Nuxt.js detected');
    if (window.React || document.querySelector('[data-reactroot]')) checks.push('React detected');
    if (window.Vue || document.querySelector('[data-v-]')) checks.push('Vue detected');
    if (window.ng || document.querySelector('[ng-version]')) checks.push('Angular detected');
    if (window.__remixContext) checks.push('Remix detected');
    // Check for state stores
    if (window.__REDUX_DEVTOOLS_EXTENSION__) checks.push('Redux DevTools available');
    if (window.__APOLLO_CLIENT__) checks.push('Apollo GraphQL detected');
    // Check meta tags for framework hints
    const generator = document.querySelector('meta[name="generator"]');
    if (generator) checks.push('Generator: ' + generator.content);
    return checks.join('\\n') || 'No major framework detected in window globals';
})()
""")
print(framework)

# 9) Intercept XHR/fetch to find API patterns - check performance entries
print("\n=== NETWORK REQUESTS (Performance API) ===")
net_requests = js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => 
        e.initiatorType === 'xmlhttprequest' || 
        e.initiatorType === 'fetch' ||
        e.name.includes('/api/') ||
        e.name.includes('/graphql')
    );
    return apis.map(e => `[${e.initiatorType}] ${e.name}`).join('\\n');
})()
""")
print(net_requests[:3000] if net_requests else "(no API requests captured)")

# 10) Also check ALL resource entries for API-like URLs
print("\n=== ALL RESOURCE URLs (filtered) ===")
all_res = js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const interesting = entries.filter(e => {
        const url = e.name.toLowerCase();
        return url.includes('/api/') || url.includes('graphql') || url.includes('.json') ||
               url.includes('account') || url.includes('billing') || url.includes('order') ||
               url.includes('payout') || url.includes('trade') || url.includes('auth') ||
               url.includes('user') || url.includes('dashboard');
    });
    return interesting.map(e => `[${e.initiatorType}] ${e.name}`).join('\\n');
})()
""")
print(all_res[:3000] if all_res else "(no interesting resources)")

ws.close()
print("\nDone.")
