"""Explore MFFU dashboard - with UTF-8 encoding fix."""
import sys, io, json, requests, websocket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

tabs = requests.get("http://127.0.0.1:9222/json").json()
mffu_tab = next(t for t in tabs if t.get("type") == "page" and "myfundedfutures" in t.get("url", "").lower())

print(f"=== MFFU TAB ===")
print(f"Title: {mffu_tab['title']}")
print(f"URL: {mffu_tab['url']}")

ws = websocket.create_connection(mffu_tab["webSocketDebuggerUrl"], timeout=30)
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

def js(expr):
    r = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    result = r.get("result", {}).get("result", {})
    return result.get("value", result.get("description", str(result)))

# Strip zero-width chars for clean output
def clean(s):
    if isinstance(s, str):
        return s.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    return s

print(f"\nURL: {js('window.location.href')}")
print(f"Title: {js('document.title')}")

# Main content - billing page
print("\n=== BILLING PAGE CONTENT ===")
print(clean(js("""
(() => {
    const body = document.body.innerText || '';
    return body.replace(/[\\u200b\\u200c\\u200d\\ufeff]/g, '').substring(0, 6000);
})()
""")))

# Account data patterns
print("\n=== ACCOUNT DATA SEARCH ===")
print(clean(js("""
(() => {
    const body = (document.body.innerText || '').replace(/[\\u200b\\u200c\\u200d\\ufeff]/g, '');
    const patterns = [
        /account[\\s#:]*[\\w-]+/gi,
        /balance[\\s:$]*[\\d,.]+/gi,
        /\\$[\\d,]+\\.\\d{2}/g,
        /profit[\\s:$]*[\\d,.]+/gi,
        /drawdown[\\s:$]*[\\d,.]+/gi,
        /funded|evaluation|challenge|breach|active|inactive|starter|expert/gi,
    ];
    let found = [];
    for (const p of patterns) {
        const matches = body.match(p);
        if (matches) found.push(...matches.slice(0, 15));
    }
    return [...new Set(found)].join('\\n') || '(none)';
})()
""")))

# Framework detection
print("\n=== FRAMEWORK DETECTION ===")
print(js("""
(() => {
    const checks = [];
    if (window.__NEXT_DATA__) checks.push('Next.js');
    if (window.__NUXT__) checks.push('Nuxt.js');
    if (window.React || document.querySelector('[data-reactroot]')) checks.push('React');
    if (window.Vue || document.querySelector('[data-v-]')) checks.push('Vue');
    if (window.ng || document.querySelector('[ng-version]')) checks.push('Angular');
    if (window.__remixContext) checks.push('Remix');
    if (window.__APOLLO_CLIENT__) checks.push('Apollo GraphQL');
    if (window.location.hash) checks.push('Hash: ' + window.location.hash);
    const meta = document.querySelector('meta[name="generator"]');
    if (meta) checks.push('Generator: ' + meta.content);
    return checks.join('\\n') || 'No framework detected';
})()
"""))

# Network requests
print("\n=== NETWORK REQUESTS (API) ===")
print(clean(js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => {
        const url = e.name.toLowerCase();
        return e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch' ||
               url.includes('/api/') || url.includes('graphql') || url.includes('.json');
    });
    const seen = new Set();
    return apis.filter(e => {
        const u = new URL(e.name);
        const key = u.origin + u.pathname;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
""")))

# All links
print("\n=== ALL LINKS ===")
print(clean(js("""
(() => {
    const links = Array.from(document.querySelectorAll('a[href]'));
    const unique = new Set();
    return links.filter(a => {
        if (unique.has(a.href)) return false;
        unique.add(a.href);
        return true;
    }).map(a => a.href + ' | ' + (a.innerText || '').trim().replace(/[\\u200b]/g,'').substring(0, 60)).join('\\n') || '(none)';
})()
""")))

# localStorage
print("\n=== LOCAL STORAGE ===")
print(clean(js("""
(() => {
    const keys = Object.keys(localStorage);
    return keys.map(k => {
        const v = localStorage.getItem(k);
        return k + ' = ' + (v ? v.substring(0, 300) : '(empty)');
    }).join('\\n') || '(empty)';
})()
""")))

# Cookies
print("\n=== COOKIES ===")
print(js("document.cookie ? document.cookie.substring(0, 1500) : '(empty/httpOnly)'"))

ws.close()
print("\nDone.")
