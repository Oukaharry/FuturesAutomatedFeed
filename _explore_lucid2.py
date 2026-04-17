"""Explore Lucid Trading dashboard via CDP on port 9222."""
import json, requests, websocket

# Find the Lucid dashboard tab (not iframe/pdf)
tabs = requests.get("http://127.0.0.1:9222/json").json()
lucid_tab = None
for t in tabs:
    url = t.get("url", "")
    typ = t.get("type", "")
    if typ == "page" and "dash.lucidtrading.com" in url and "pdf" not in url:
        lucid_tab = t
        break

if not lucid_tab:
    print("ERROR: No Lucid Trading dashboard tab found.")
    for t in tabs:
        print(f"  [{t.get('type')}] {t.get('title','?')[:60]} | {t.get('url','')[:80]}")
    exit(1)

print(f"=== LUCID TAB ===")
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

# 2) Nav/sidebar
print("\n=== NAV / SIDEBAR ===")
print(js("""
(() => {
    const sels = ['nav', '[class*="sidebar"]', '[class*="nav"]', '[class*="menu"]', 
                  '[role="navigation"]', '.sidebar', '#sidebar', '[class*="Sidebar"]',
                  '[class*="drawer"]', '[class*="Drawer"]'];
    let results = [];
    for (const sel of sels) {
        document.querySelectorAll(sel).forEach(el => {
            const text = el.innerText.trim().substring(0, 500);
            if (text && text.length > 5) results.push('[' + sel + '] ' + text);
        });
    }
    return results.join('\\n---\\n') || '(none found)';
})()
"""))

# 3) Main page text
print("\n=== MAIN CONTENT ===")
print(js("""
(() => {
    const sels = ['main', '[class*="content"]', '[class*="dashboard"]', '[role="main"]', '#root', '#app', '.app'];
    for (const sel of sels) {
        const el = document.querySelector(sel);
        if (el) {
            const text = el.innerText.trim().substring(0, 4000);
            if (text.length > 20) return '[' + sel + '] ' + text;
        }
    }
    return document.body.innerText.trim().substring(0, 4000);
})()
"""))

# 4) Account data patterns
print("\n=== ACCOUNT DATA SEARCH ===")
print(js("""
(() => {
    const body = document.body.innerText;
    const patterns = [
        /account[\\s#:]*[\\w-]+/gi,
        /balance[\\s:$]*[\\d,.]+/gi,
        /\\$[\\d,]+\\.\\d{2}/g,
        /profit[\\s:$]*[\\d,.]+/gi,
        /loss[\\s:$]*[\\d,.]+/gi,
        /drawdown[\\s:$]*[\\d,.]+/gi,
        /funded|evaluation|challenge|breach|active|inactive/gi,
    ];
    let found = [];
    for (const p of patterns) {
        const matches = body.match(p);
        if (matches) found.push(...matches.slice(0, 15));
    }
    return [...new Set(found)].join('\\n') || '(none)';
})()
"""))

# 5) Framework detection
print("\n=== FRAMEWORK DETECTION ===")
print(js("""
(() => {
    const checks = [];
    if (window.__NEXT_DATA__) checks.push('Next.js');
    if (window.__NUXT__) checks.push('Nuxt.js');
    if (window.React || document.querySelector('[data-reactroot]')) checks.push('React');
    if (window.Vue || document.querySelector('[data-v-]')) checks.push('Vue');
    if (window.ng || document.querySelector('[ng-version]')) checks.push('Angular: ' + (document.querySelector('[ng-version]')?.getAttribute('ng-version') || ''));
    if (window.__remixContext) checks.push('Remix');
    if (window.__REDUX_DEVTOOLS_EXTENSION__) checks.push('Redux DevTools');
    if (window.__APOLLO_CLIENT__) checks.push('Apollo GraphQL');
    // Check for hash routing (Vue/Angular common)
    if (window.location.hash) checks.push('Hash routing: ' + window.location.hash);
    return checks.join('\\n') || 'No major framework detected';
})()
"""))

# 6) Network requests from Performance API
print("\n=== NETWORK REQUESTS (Performance API) ===")
print(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch' ||
               url.includes('/api/') || url.includes('graphql') || url.includes('.json') ||
               url.includes('account') || url.includes('billing') || url.includes('trade') ||
               url.includes('auth') || url.includes('user') || url.includes('dashboard') ||
               url.includes('payout');
    });
    return apis.map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
"""))

# 7) All links
print("\n=== ALL LINKS ===")
print(js("""
(() => {
    const links = Array.from(document.querySelectorAll('a[href]'));
    return links.map(a => a.href + ' | ' + a.innerText.trim().substring(0, 60)).join('\\n') || '(none)';
})()
"""))

# 8) localStorage keys
print("\n=== LOCAL STORAGE ===")
print(js("""
(() => {
    const keys = Object.keys(localStorage);
    return keys.map(k => {
        const v = localStorage.getItem(k);
        return k + ' = ' + (v ? v.substring(0, 200) : '(empty)');
    }).join('\\n') || '(empty)';
})()
"""))

# 9) sessionStorage keys
print("\n=== SESSION STORAGE ===")
print(js("""
(() => {
    const keys = Object.keys(sessionStorage);
    return keys.map(k => {
        const v = sessionStorage.getItem(k);
        return k + ' = ' + (v ? v.substring(0, 200) : '(empty)');
    }).join('\\n') || '(empty)';
})()
"""))

# 10) Check for tokens in cookies or headers
print("\n=== COOKIES (document.cookie) ===")
print(js("document.cookie || '(empty/httpOnly)'"))

# 11) Try to find any global app state / store
print("\n=== GLOBAL STATE SEARCH ===")
print(js("""
(() => {
    const checks = [];
    // Vue store
    const app = document.querySelector('#app');
    if (app && app.__vue_app__) {
        checks.push('Vue app instance found');
        const store = app.__vue_app__.config.globalProperties.$store;
        if (store) {
            checks.push('Vuex store state keys: ' + Object.keys(store.state).join(', '));
        }
    }
    // Angular
    const ngRoot = document.querySelector('[ng-version]') || document.querySelector('app-root');
    if (ngRoot) checks.push('Angular root found');
    // Try window globals
    for (const key of Object.keys(window)) {
        if (key.startsWith('__') || key.startsWith('_app') || key.includes('store') || key.includes('Store')) {
            const val = window[key];
            if (val && typeof val === 'object') {
                checks.push('window.' + key + ' = ' + JSON.stringify(val).substring(0, 200));
            }
        }
    }
    return checks.join('\\n') || '(no global state found)';
})()
"""))

ws.close()
print("\nDone.")
