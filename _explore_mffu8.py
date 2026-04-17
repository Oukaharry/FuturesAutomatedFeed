"""Deep dive into MFFU payouts chunk + new API endpoints."""
import sys, io, json, requests, websocket, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

tabs = requests.get("http://127.0.0.1:9222/json").json()
mffu_tab = next(t for t in tabs if t.get("type") == "page" and "myfundedfutures" in t.get("url", "").lower())
ws = websocket.create_connection(mffu_tab["webSocketDebuggerUrl"], timeout=60)
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

# Navigate to payouts page
js("window.location.href = 'https://myfundedfutures.com/payouts'")
time.sleep(5)

# 1) Fetch the payouts chunk and search for fetch/axios/API call patterns
print("=== PAYOUTS CHUNK - FETCH/API CALLS ===")
print(js("""
(async () => {
    const payoutChunkUrl = Array.from(document.querySelectorAll('script[src]'))
        .map(s => s.src)
        .find(s => s.includes('payouts'));
    
    if (!payoutChunkUrl) return 'No payouts chunk found';
    
    const resp = await fetch(payoutChunkUrl);
    const text = await resp.text();
    
    // Find all fetch/get/post calls and their URLs
    const results = [];
    
    // Look for API URL strings
    const urlMatches = text.match(/["'`][^"'`]*(?:api|fetch|get|post)[^"'`]*["'`]/gi) || [];
    const apiUrls = urlMatches.filter(m => 
        m.includes('/api/') || m.includes('https://') || m.includes('concat(')
    );
    results.push('API URL strings: ' + [...new Set(apiUrls)].slice(0, 20).join('\\n'));
    
    // Look for string concatenation with 'api'
    const concatMatches = text.match(/concat\([^)]*api[^)]*\)/gi) || [];
    results.push('\\nConcat with api: ' + concatMatches.slice(0, 10).join('\\n'));
    
    // Look for useEffect/useSWR/useQuery patterns near 'payout'
    let idx = 0;
    while (true) {
        idx = text.indexOf('payout', idx);
        if (idx === -1) break;
        const context = text.substring(Math.max(0, idx - 300), idx + 300);
        // Check if this context has a fetch/get/post/useQuery
        if (context.match(/fetch|\.get|\.post|useQuery|useSWR|axios|getPayouts|withdrawals/i)) {
            results.push('\\nFETCH near payout: ...' + context.replace(/\\n/g, ' ').substring(0, 500));
        }
        idx += 6;
    }
    
    return results.join('\\n') || '(nothing found)';
})()
"""))

# 2) Search the shared chunk (1298) for API calls
print("\n=== SHARED CHUNK 1298 - PAYOUT API CALLS ===")
print(js("""
(async () => {
    const chunkUrl = Array.from(document.querySelectorAll('script[src]'))
        .map(s => s.src)
        .find(s => s.includes('1298'));
    
    if (!chunkUrl) {
        // Try fetching it directly
        const entries = performance.getEntriesByType('resource')
            .filter(e => e.name.includes('1298'));
        if (entries.length) {
            const resp = await fetch(entries[0].name);
            const text = await resp.text();
            
            // Find fetch/API patterns
            const results = [];
            let idx = 0;
            while (true) {
                idx = text.toLowerCase().indexOf('payout', idx);
                if (idx === -1) break;
                const context = text.substring(Math.max(0, idx - 300), idx + 300);
                if (context.match(/fetch|axiosInstance|api\\.|httpService|apiService|\\$http|\\.get\\(|\\.post\\(/i)) {
                    results.push('...' + context.replace(/\\n/g, ' ').substring(0, 500) + '...');
                }
                idx += 6;
            }
            return results.join('\\n---\\n') || '(no fetch patterns near payout)';
        }
        return 'Chunk not found';
    }
    
    const resp = await fetch(chunkUrl);
    const text = await resp.text();
    let results = [];
    let idx = 0;
    while (true) {
        idx = text.toLowerCase().indexOf('getpayout', idx);
        if (idx === -1) break;
        results.push(text.substring(Math.max(0, idx-200), idx+200));
        idx += 9;
    }
    return results.join('\\n---\\n') || '(no getpayout found)';
})()
"""))

# 3) Try propbackend API
print("\n=== PROPBACKEND API ===")
print(js("""
(async () => {
    const resp = await fetch('https://api.propbackend.com/api/', { credentials: 'include' });
    return resp.status + ' | ' + (await resp.text()).substring(0, 2000);
})()
"""))

# 4) Try PGW endpoints
print("\n=== PGW TOKEN ===")
print(js("""
(async () => {
    const resp = await fetch('https://api.myfundedfutures.com/pgw/token', { credentials: 'include' });
    return resp.status + ' | ' + (await resp.text()).substring(0, 2000);
})()
"""))

# 5) Look for axios instance / httpService in window
print("\n=== GLOBAL API SERVICE ===")
print(js("""
(() => {
    const names = ['axios', 'apiService', 'httpService', 'api', 'client', 'axiosInstance'];
    const found = [];
    for (const n of names) {
        if (window[n]) found.push(n + ': ' + typeof window[n]);
    }
    return found.join('\\n') || '(no global API service)';
})()
"""))

# 6) Search DEEPER in React fiber for component tree
print("\n=== REACT COMPONENT TREE ===")
print(js("""
(() => {
    const root = document.getElementById('__next');
    if (!root) return 'no root';
    
    const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber'));
    if (!fiberKey) return 'no fiber';
    
    let fiber = root[fiberKey];
    const components = [];
    let visited = 0;
    
    function traverse(f, depth) {
        if (!f || depth > 50 || visited > 500) return;
        visited++;
        
        const name = f.type?.displayName || f.type?.name || '';
        if (name) {
            components.push('  '.repeat(depth) + name);
        }
        
        // Check for hooks state (data fetching)
        let state = f.memoizedState;
        let hookIdx = 0;
        while (state && hookIdx < 20) {
            hookIdx++;
            if (state.queue && state.memoizedState && typeof state.memoizedState === 'object') {
                const stateStr = JSON.stringify(state.memoizedState);
                if (stateStr.length > 100 && stateStr.includes('payout')) {
                    components.push('  '.repeat(depth+1) + 'HAS PAYOUT DATA: ' + stateStr.substring(0, 500));
                }
            }
            state = state.next;
        }
        
        if (f.child) traverse(f.child, depth + 1);
        if (f.sibling) traverse(f.sibling, depth);
    }
    
    traverse(fiber, 0);
    return components.filter(c => c.trim()).join('\\n') || '(empty)';
})()
"""))

# 7) Check if there's a WebSocket connection carrying payout data
print("\n=== WS CONNECTION CHECK ===")
print(js("""
(() => {
    // Check if there's a WS connection on the page
    const perf = performance.getEntriesByType('resource')
        .filter(e => e.name.startsWith('wss://') || e.name.startsWith('ws://'))
        .map(e => e.name);
    return perf.join('\\n') || '(no WS in performance entries)';
})()
"""))

js("window.location.href = 'https://myfundedfutures.com/billing'")
ws.close()
print("\nDone.")
