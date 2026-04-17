"""
Thorough analysis of all open Tradovate pages via CDP.
Discovers: tabs, APIs, cookies, auth tokens, DOM data, WebSocket connections.
Passive/read-only — does NOT click or modify anything.
"""
import json, urllib.request, websocket, time, sys

CDP_PORT = 9222

def get_tabs():
    """List all Chrome tabs."""
    data = urllib.request.urlopen(f'http://localhost:{CDP_PORT}/json').read()
    return json.loads(data)

def send_cdp(ws, method, params=None, timeout=5):
    """Send a CDP command and wait for result."""
    msg_id = int(time.time() * 1000) % 1000000
    msg = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ws.settimeout(min(1, deadline - time.time()))
            resp = json.loads(ws.recv())
            if resp.get("id") == msg_id:
                return resp.get("result", {})
        except websocket.WebSocketTimeoutException:
            continue
    return None

def analyze_tab(tab):
    """Connect to a tab and extract all useful data."""
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    
    ws = websocket.create_connection(ws_url, timeout=10)
    results = {}
    
    try:
        # 1. Get cookies for this tab's domain
        cookies_resp = send_cdp(ws, "Network.getCookies")
        if cookies_resp:
            cookies = cookies_resp.get("cookies", [])
            results["cookies"] = []
            for c in cookies:
                results["cookies"].append({
                    "name": c["name"],
                    "domain": c.get("domain", ""),
                    "value": c["value"][:50] + "..." if len(c.get("value", "")) > 50 else c.get("value", ""),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "path": c.get("path", "/"),
                })
        
        # 2. Check localStorage for auth tokens
        ls_script = """
        (() => {
            let items = {};
            for (let i = 0; i < localStorage.length; i++) {
                let key = localStorage.key(i);
                let val = localStorage.getItem(key);
                if (val && val.length > 500) val = val.substring(0, 500) + '...TRUNCATED';
                items[key] = val;
            }
            return JSON.stringify(items);
        })()
        """
        ls_resp = send_cdp(ws, "Runtime.evaluate", {"expression": ls_script, "returnByValue": True})
        if ls_resp and ls_resp.get("result", {}).get("value"):
            try:
                results["localStorage"] = json.loads(ls_resp["result"]["value"])
            except:
                results["localStorage"] = ls_resp["result"]["value"]
        
        # 3. Check sessionStorage
        ss_script = """
        (() => {
            let items = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                let key = sessionStorage.key(i);
                let val = sessionStorage.getItem(key);
                if (val && val.length > 500) val = val.substring(0, 500) + '...TRUNCATED';
                items[key] = val;
            }
            return JSON.stringify(items);
        })()
        """
        ss_resp = send_cdp(ws, "Runtime.evaluate", {"expression": ss_script, "returnByValue": True})
        if ss_resp and ss_resp.get("result", {}).get("value"):
            try:
                results["sessionStorage"] = json.loads(ss_resp["result"]["value"])
            except:
                results["sessionStorage"] = ss_resp["result"]["value"]
        
        # 4. Intercept XHR/fetch — check performance entries for API calls already made
        perf_script = """
        (() => {
            let entries = performance.getEntriesByType('resource');
            let apis = entries.filter(e => 
                (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') ||
                e.name.includes('/api/') || e.name.includes('/v1/') || e.name.includes('/v2/')
            ).map(e => ({
                url: e.name,
                type: e.initiatorType,
                duration: Math.round(e.duration),
                size: e.transferSize || 0
            }));
            return JSON.stringify(apis);
        })()
        """
        perf_resp = send_cdp(ws, "Runtime.evaluate", {"expression": perf_script, "returnByValue": True})
        if perf_resp and perf_resp.get("result", {}).get("value"):
            try:
                results["apiCalls"] = json.loads(perf_resp["result"]["value"])
            except:
                results["apiCalls"] = perf_resp["result"]["value"]
        
        # 5. Check for WebSocket connections
        ws_script = """
        (() => {
            // Check if there are any global references to websockets
            let wsInfo = [];
            // Common patterns for WS storage
            if (window._ws) wsInfo.push('window._ws: ' + window._ws.url);
            if (window.socket) wsInfo.push('window.socket: ' + (window.socket.url || 'exists'));
            if (window.__NEXT_DATA__) wsInfo.push('__NEXT_DATA__ found (Next.js app)');
            if (window.__NUXT__) wsInfo.push('__NUXT__ found');
            
            // Check for Redux store
            if (window.__REDUX_DEVTOOLS_EXTENSION__) wsInfo.push('Redux DevTools available');
            if (window.store) wsInfo.push('window.store found');
            if (window.__store) wsInfo.push('window.__store found');
            
            // Check for React
            let rootEl = document.getElementById('root') || document.getElementById('app') || document.getElementById('__next');
            if (rootEl) {
                let fiberKey = Object.keys(rootEl).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (fiberKey) wsInfo.push('React app detected (fiber key: ' + fiberKey.substring(0, 30) + ')');
            }
            
            return JSON.stringify(wsInfo);
        })()
        """
        ws_resp = send_cdp(ws, "Runtime.evaluate", {"expression": ws_script, "returnByValue": True})
        if ws_resp and ws_resp.get("result", {}).get("value"):
            try:
                results["frameworkInfo"] = json.loads(ws_resp["result"]["value"])
            except:
                results["frameworkInfo"] = ws_resp["result"]["value"]
        
        # 6. Get page title and current URL
        url_resp = send_cdp(ws, "Runtime.evaluate", {"expression": "document.title + '|||' + window.location.href", "returnByValue": True})
        if url_resp:
            val = url_resp.get("result", {}).get("value", "")
            parts = val.split("|||")
            results["title"] = parts[0] if parts else ""
            results["url"] = parts[1] if len(parts) > 1 else ""
        
        # 7. Check for global API/auth objects
        globals_script = """
        (() => {
            let found = {};
            // Common auth patterns
            let authKeys = ['token', 'accessToken', 'access_token', 'authToken', 'auth_token', 
                           'jwt', 'bearer', 'apiKey', 'api_key', 'session', 'csrfToken',
                           'Authorization', 'x-api-key'];
            for (let key of authKeys) {
                if (window[key]) found['window.' + key] = String(window[key]).substring(0, 80);
            }
            
            // Check meta tags for API config
            let metas = document.querySelectorAll('meta[name], meta[property]');
            metas.forEach(m => {
                let name = m.getAttribute('name') || m.getAttribute('property') || '';
                if (name.toLowerCase().includes('api') || name.toLowerCase().includes('token') || name.toLowerCase().includes('csrf')) {
                    found['meta:' + name] = (m.getAttribute('content') || '').substring(0, 80);
                }
            });
            
            return JSON.stringify(found);
        })()
        """
        globals_resp = send_cdp(ws, "Runtime.evaluate", {"expression": globals_script, "returnByValue": True})
        if globals_resp and globals_resp.get("result", {}).get("value"):
            try:
                results["authObjects"] = json.loads(globals_resp["result"]["value"])
            except:
                results["authObjects"] = globals_resp["result"]["value"]

        # 8. Get all navigation links / menu items for automation mapping
        nav_script = """
        (() => {
            let navItems = [];
            // Look for nav links, tabs, menu items
            let selectors = ['nav a', '.nav a', '[role="tab"]', '.tab', '.menu-item a', 
                           'a[href*="report"]', 'a[href*="account"]', 'a[href*="history"]',
                           'a[href*="fill"]', 'a[href*="order"]', 'a[href*="position"]',
                           'a[href*="performance"]', 'a[href*="cash"]',
                           'button', '[role="button"]'];
            for (let sel of selectors) {
                document.querySelectorAll(sel).forEach(el => {
                    let text = (el.textContent || '').trim().substring(0, 60);
                    let href = el.getAttribute('href') || '';
                    let id = el.id || '';
                    let cls = (el.className || '').toString().substring(0, 60);
                    if (text && text.length > 1 && text.length < 60) {
                        navItems.push({text, href, id, tag: el.tagName, class: cls});
                    }
                });
            }
            // Deduplicate by text
            let seen = new Set();
            return JSON.stringify(navItems.filter(n => {
                let key = n.text + n.href;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            }));
        })()
        """
        nav_resp = send_cdp(ws, "Runtime.evaluate", {"expression": nav_script, "returnByValue": True})
        if nav_resp and nav_resp.get("result", {}).get("value"):
            try:
                results["navigation"] = json.loads(nav_resp["result"]["value"])
            except:
                pass

        # 9. Get visible account info / data tables
        data_script = """
        (() => {
            let data = {};
            
            // Tables
            let tables = document.querySelectorAll('table');
            data.tableCount = tables.length;
            data.tables = [];
            tables.forEach((t, i) => {
                let headers = Array.from(t.querySelectorAll('th')).map(h => h.textContent.trim());
                let rowCount = t.querySelectorAll('tbody tr').length;
                data.tables.push({index: i, headers, rowCount});
            });
            
            // Look for account-related text
            let accountTexts = [];
            document.querySelectorAll('[class*="account"], [class*="Account"], [id*="account"], [id*="Account"]').forEach(el => {
                let text = (el.textContent || '').trim().substring(0, 100);
                if (text) accountTexts.push(text);
            });
            data.accountElements = accountTexts.slice(0, 20);
            
            // Look for dropdown/select options (account selectors)
            let selects = document.querySelectorAll('select');
            data.selects = [];
            selects.forEach(s => {
                let opts = Array.from(s.options).map(o => ({value: o.value, text: o.textContent.trim()}));
                data.selects.push({id: s.id, name: s.name, class: (s.className||'').substring(0,50), options: opts.slice(0, 20)});
            });
            
            return JSON.stringify(data);
        })()
        """
        data_resp = send_cdp(ws, "Runtime.evaluate", {"expression": data_script, "returnByValue": True})
        if data_resp and data_resp.get("result", {}).get("value"):
            try:
                results["pageData"] = json.loads(data_resp["result"]["value"])
            except:
                pass

    finally:
        ws.close()
    
    return results


def enable_network_monitoring(tab, duration=8):
    """Enable network monitoring to capture live API calls for a few seconds."""
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return []
    
    ws = websocket.create_connection(ws_url, timeout=10)
    captured = []
    
    try:
        # Enable network monitoring
        send_cdp(ws, "Network.enable", {"maxTotalBufferSize": 10000000})
        
        print(f"  Monitoring network for {duration}s...")
        deadline = time.time() + duration
        while time.time() < deadline:
            try:
                ws.settimeout(0.5)
                msg = json.loads(ws.recv())
                method = msg.get("method", "")
                params = msg.get("params", {})
                
                if method == "Network.requestWillBeSent":
                    req = params.get("request", {})
                    url = req.get("url", "")
                    # Filter for API-like requests
                    if any(kw in url.lower() for kw in ['/api/', '/v1/', '/v2/', 'graphql', '.json', 
                                                         'account', 'position', 'order', 'fill', 
                                                         'report', 'history', 'balance', 'trade',
                                                         'auth', 'token', 'session']):
                        captured.append({
                            "url": url[:200],
                            "method": req.get("method", "GET"),
                            "headers": {k: v[:80] for k, v in list(req.get("headers", {}).items())[:10]},
                            "hasBody": bool(params.get("request", {}).get("postData")),
                        })
                
                elif method == "Network.webSocketCreated":
                    captured.append({
                        "type": "WebSocket",
                        "url": params.get("url", "")[:200],
                    })
                    
            except websocket.WebSocketTimeoutException:
                continue
        
        send_cdp(ws, "Network.disable")
    finally:
        ws.close()
    
    return captured


# ============ MAIN ============
if __name__ == "__main__":
    print("=" * 80)
    print("TRADOVATE PAGE ANALYSIS — Passive CDP Inspection")
    print("=" * 80)
    
    tabs = get_tabs()
    tradovate_tabs = [t for t in tabs if 'tradovate' in (t.get('url', '') + t.get('title', '')).lower()]
    
    print(f"\nFound {len(tabs)} total tabs, {len(tradovate_tabs)} Tradovate-related:\n")
    
    for i, tab in enumerate(tradovate_tabs):
        print(f"\n{'='*80}")
        print(f"TAB {i+1}: {tab.get('title', 'No Title')}")
        print(f"  URL: {tab.get('url', '')}")
        print(f"{'='*80}")
        
        info = analyze_tab(tab)
        if not info:
            print("  Could not connect to tab")
            continue
        
        # Auth / Cookies
        print(f"\n  --- COOKIES ({len(info.get('cookies', []))} total) ---")
        for c in info.get("cookies", []):
            flag = "🔑" if any(kw in c["name"].lower() for kw in ["token", "auth", "session", "jwt", "csrf"]) else "  "
            print(f"  {flag} {c['name']} = {c['value']}  [domain={c['domain']}]")
        
        # LocalStorage
        ls = info.get("localStorage", {})
        if ls:
            print(f"\n  --- LOCAL STORAGE ({len(ls)} keys) ---")
            for k, v in ls.items():
                flag = "🔑" if any(kw in k.lower() for kw in ["token", "auth", "session", "jwt", "access"]) else "  "
                display_v = str(v)[:120]
                print(f"  {flag} {k} = {display_v}")
        
        # SessionStorage 
        ss = info.get("sessionStorage", {})
        if ss:
            print(f"\n  --- SESSION STORAGE ({len(ss)} keys) ---")
            for k, v in ss.items():
                display_v = str(v)[:120]
                print(f"    {k} = {display_v}")
        
        # Auth objects
        auth = info.get("authObjects", {})
        if auth:
            print(f"\n  --- AUTH OBJECTS ---")
            for k, v in auth.items():
                print(f"  🔑 {k} = {v}")
        
        # Framework info
        fw = info.get("frameworkInfo", [])
        if fw:
            print(f"\n  --- FRAMEWORK INFO ---")
            for f_item in fw:
                print(f"    {f_item}")
        
        # API calls from performance entries
        apis = info.get("apiCalls", [])
        if apis:
            # Deduplicate by URL base
            seen_urls = set()
            unique_apis = []
            for a in apis:
                # Strip query params for dedup
                base_url = a["url"].split("?")[0]
                if base_url not in seen_urls:
                    seen_urls.add(base_url)
                    unique_apis.append(a)
            
            print(f"\n  --- API CALLS DETECTED ({len(unique_apis)} unique endpoints) ---")
            for a in unique_apis:
                print(f"    [{a.get('type','?')}] {a['url'][:150]}")
        
        # Navigation / menu items
        nav = info.get("navigation", [])
        if nav:
            print(f"\n  --- NAVIGATION ITEMS ({len(nav)}) ---")
            for n in nav[:30]:
                href = f" → {n['href']}" if n.get('href') and n['href'] != '#' else ""
                print(f"    [{n['tag']}] {n['text']}{href}")
        
        # Page data (tables, accounts, selects)
        pd = info.get("pageData", {})
        if pd:
            print(f"\n  --- PAGE DATA ---")
            print(f"    Tables: {pd.get('tableCount', 0)}")
            for t in pd.get("tables", []):
                print(f"      Table {t['index']}: {t['rowCount']} rows, headers: {t['headers']}")
            
            if pd.get("selects"):
                print(f"    Select dropdowns:")
                for s in pd["selects"]:
                    print(f"      {s.get('id') or s.get('name') or s.get('class')}: {[o['text'] for o in s.get('options', [])]}")
            
            if pd.get("accountElements"):
                print(f"    Account-related elements:")
                for ae in pd["accountElements"][:10]:
                    print(f"      {ae[:100]}")
    
    # Now monitor network on the first Tradovate tab
    if tradovate_tabs:
        print(f"\n{'='*80}")
        print("LIVE NETWORK MONITORING (8 seconds) — capturing API calls...")
        print(f"{'='*80}")
        
        captured = enable_network_monitoring(tradovate_tabs[0], duration=8)
        if captured:
            print(f"\n  Captured {len(captured)} API-like requests:")
            for c in captured:
                if c.get("type") == "WebSocket":
                    print(f"    [WS] {c['url']}")
                else:
                    print(f"    [{c['method']}] {c['url']}")
                    if c.get("headers"):
                        auth_headers = {k: v for k, v in c["headers"].items() 
                                       if any(a in k.lower() for a in ["auth", "token", "api-key", "bearer"])}
                        if auth_headers:
                            print(f"         Auth: {auth_headers}")
        else:
            print("  No API calls captured during monitoring period")
    
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")
