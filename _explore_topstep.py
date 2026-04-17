"""Explore TopStep dashboard via CDP on port 9222."""
import json, requests, websocket

# Find the TopStep tab
tabs = requests.get("http://127.0.0.1:9222/json").json()
topstep_tab = None
for t in tabs:
    url = t.get("url", "")
    typ = t.get("type", "")
    title = t.get("title", "")
    if typ == "page" and ("topstep" in url.lower() or "topstep" in title.lower()):
        topstep_tab = t
        print(f"Found: [{typ}] {title[:60]} | {url[:80]}")

if not topstep_tab:
    print("ERROR: No TopStep tab found. Available tabs:")
    for t in tabs:
        print(f"  [{t.get('type')}] {t.get('title','?')[:60]} | {t.get('url','')[:80]}")
    exit(1)

print(f"\n=== TOPSTEP TAB ===")
print(f"Title: {topstep_tab['title']}")
print(f"URL: {topstep_tab['url']}")
ws_url = topstep_tab["webSocketDebuggerUrl"]

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

def js(expr, await_promise=False):
    r = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
    result = r.get("result", {}).get("result", {})
    if result.get("type") == "undefined":
        return None
    val = result.get("value", result.get("description", str(result)))
    return val

# 1) Current state
print(f"\nURL: {js('window.location.href')}")
print(f"Title: {js('document.title')}")

# 2) Check if still on login page
is_login = js("window.location.href.includes('login')")
print(f"On login page: {is_login}")

if is_login:
    print("\nStill on login page - user needs to log in first.")
    ws.close()
    exit(0)

# 3) Nav/sidebar
print("\n=== NAV / SIDEBAR ===")
print(js("""
(() => {
    const sels = ['nav', '[class*="sidebar"]', '[class*="nav"]', '[class*="menu"]', 
                  '[role="navigation"]', '.sidebar', '#sidebar', '[class*="Sidebar"]',
                  '[class*="drawer"]', '[class*="Drawer"]', 'aside'];
    let results = [];
    for (const sel of sels) {
        document.querySelectorAll(sel).forEach(el => {
            if (!el) return;
            const text = (el.innerText || '').trim().substring(0, 500);
            if (text && text.length > 5) results.push('[' + sel + '] ' + text);
        });
    }
    return results.join('\\n---\\n') || '(none found)';
})()
"""))

# 4) Main content
print("\n=== MAIN CONTENT ===")
print(js("""
(() => {
    const sels = ['main', '[class*="content"]', '[class*="dashboard"]', '[role="main"]', '#root', '#app', '#__next'];
    for (const sel of sels) {
        const el = document.querySelector(sel);
        if (el) {
            const text = (el.innerText || '').trim().substring(0, 4000);
            if (text.length > 20) return '[' + sel + '] ' + text;
        }
    }
    return (document.body.innerText || '').trim().substring(0, 4000);
})()
"""))

# 5) Account data patterns
print("\n=== ACCOUNT DATA SEARCH ===")
print(js("""
(() => {
    const body = document.body.innerText || '';
    const patterns = [
        /account[\\s#:]*[\\w-]+/gi,
        /balance[\\s:$]*[\\d,.]+/gi,
        /\\$[\\d,]+\\.\\d{2}/g,
        /profit[\\s:$]*[\\d,.]+/gi,
        /loss[\\s:$]*[\\d,.]+/gi,
        /drawdown[\\s:$]*[\\d,.]+/gi,
        /funded|evaluation|challenge|breach|active|inactive|step\\s*\\d/gi,
    ];
    let found = [];
    for (const p of patterns) {
        const matches = body.match(p);
        if (matches) found.push(...matches.slice(0, 15));
    }
    return [...new Set(found)].join('\\n') || '(none)';
})()
"""))

# 6) Framework detection
print("\n=== FRAMEWORK DETECTION ===")
print(js("""
(() => {
    const checks = [];
    if (window.__NEXT_DATA__) checks.push('Next.js: ' + JSON.stringify(window.__NEXT_DATA__).substring(0, 500));
    if (window.__NUXT__) checks.push('Nuxt.js');
    if (window.React || document.querySelector('[data-reactroot]')) checks.push('React');
    if (window.Vue || document.querySelector('[data-v-]')) checks.push('Vue');
    if (window.ng || document.querySelector('[ng-version]')) checks.push('Angular: ' + (document.querySelector('[ng-version]')?.getAttribute('ng-version') || ''));
    if (window.__remixContext) checks.push('Remix');
    if (window.__REDUX_DEVTOOLS_EXTENSION__) checks.push('Redux DevTools');
    if (window.__APOLLO_CLIENT__) checks.push('Apollo GraphQL');
    if (window.location.hash) checks.push('Hash routing: ' + window.location.hash);
    return checks.join('\\n') || 'No major framework detected';
})()
"""))

# 7) Network requests (Performance API)
print("\n=== NETWORK REQUESTS (API calls) ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch' ||
               url.includes('/api/') || url.includes('graphql') || url.includes('.json');
    });
    return apis.map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
"""))

# 8) All links
print("\n=== ALL LINKS ===")
print(js("""
(() => {
    const links = Array.from(document.querySelectorAll('a[href]'));
    const unique = new Set();
    return links.filter(a => {
        const key = a.href + '|' + a.innerText.trim().substring(0, 30);
        if (unique.has(key)) return false;
        unique.add(key);
        return true;
    }).map(a => a.href + ' | ' + a.innerText.trim().substring(0, 60)).join('\\n') || '(none)';
})()
"""))

# 9) localStorage
print("\n=== LOCAL STORAGE ===")
print(js("""
(() => {
    const keys = Object.keys(localStorage);
    return keys.map(k => {
        const v = localStorage.getItem(k);
        return k + ' = ' + (v ? v.substring(0, 300) : '(empty)');
    }).join('\\n') || '(empty)';
})()
"""))

# 10) Cookies
print("\n=== COOKIES ===")
print(js("document.cookie ? document.cookie.substring(0, 1500) : '(empty/httpOnly)'"))

ws.close()
print("\nDone.")
