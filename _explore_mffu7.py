"""Search MFFU Next.js chunks for payout API endpoint names - fixed escapes."""
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

# Navigate to payouts first
print("=== NAVIGATING TO PAYOUTS ===")
js("window.location.href = 'https://myfundedfutures.com/payouts'")
time.sleep(5)
print(f"URL: {js('window.location.href')}")

# Search all loaded webpack chunks for API patterns  
print("\n=== SEARCHING ALL LOADED CHUNKS FOR API ENDPOINTS ===")
print(js("""
(async () => {
    const entries = performance.getEntriesByType('resource')
        .filter(e => e.name.includes('_next/static/chunks') && e.name.endsWith('.js'));
    const results = [];
    
    for (const entry of entries) {
        try {
            const resp = await fetch(entry.name);
            const text = await resp.text();
            
            // Search for any string containing 'api' near 'payout' or 'withdraw'  
            const matches = [];
            const idx1 = text.toLowerCase().indexOf('payout');
            if (idx1 >= 0) {
                matches.push('PAYOUT context: ' + text.substring(Math.max(0, idx1-100), idx1+200).replace(/\\n/g,' '));
            }
            const idx2 = text.toLowerCase().indexOf('withdraw');
            if (idx2 >= 0) {
                matches.push('WITHDRAW context: ' + text.substring(Math.max(0, idx2-100), idx2+200).replace(/\\n/g,' '));
            }
            const idx3 = text.toLowerCase().indexOf('getpayout');
            if (idx3 >= 0) {
                matches.push('GETPAYOUT context: ' + text.substring(Math.max(0, idx3-100), idx3+200).replace(/\\n/g,' '));
            }
            
            if (matches.length > 0) {
                const name = entry.name.split('/').pop();
                results.push(name + ':\\n' + matches.join('\\n'));
            }
        } catch(e) {}
    }
    return results.join('\\n---\\n') || '(no matches)';
})()
"""))

# Try to find all API endpoints in the main app chunk
print("\n=== ALL API ENDPOINTS IN CHUNKS ===")
print(js("""
(async () => {
    const entries = performance.getEntriesByType('resource')
        .filter(e => e.name.includes('_next/static/chunks') && e.name.endsWith('.js'));
    const allApis = new Set();
    
    for (const entry of entries) {
        try {
            const resp = await fetch(entry.name);
            const text = await resp.text();
            
            // Match any string that looks like an API path
            const apiPattern = /["']((?:\\/api\\/|https?:\\/\\/api\\.)[^"'\\s]+)["']/gi;
            let m;
            while ((m = apiPattern.exec(text)) !== null) {
                allApis.add(m[1]);
            }
        } catch(e) {}
    }
    return [...allApis].sort().join('\\n') || '(none)';
})()
"""))

# Check if payout data might come via WebSocket
print("\n=== WS TOKEN ===")
print(js("""
(async () => {
    const resp = await fetch('https://api.myfundedfutures.com/api/getWSToken/', { credentials: 'include' });
    const data = await resp.json();
    return JSON.stringify(data).substring(0, 500);
})()
"""))

# Check for any React state/context with payout data
print("\n=== REACT FIBER PAYOUT DATA ===")
print(js("""
(() => {
    function findReactData(el, depth=0) {
        if (!el || depth > 30) return null;
        const keys = Object.keys(el);
        for (const key of keys) {
            if (key.startsWith('__reactFiber') || key.startsWith('__reactInternalInstance')) {
                let fiber = el[key];
                let visited = 0;
                while (fiber && visited < 200) {
                    visited++;
                    const state = fiber.memoizedState;
                    const props = fiber.memoizedProps;
                    
                    // Check props for payout data
                    if (props && typeof props === 'object') {
                        const str = JSON.stringify(props).toLowerCase();
                        if (str.includes('payout') || str.includes('withdrawal')) {
                            return 'PROPS: ' + JSON.stringify(props).substring(0, 2000);
                        }
                    }
                    
                    // Check state for payout data
                    if (state && typeof state === 'object') {
                        const str = JSON.stringify(state).toLowerCase();
                        if (str.includes('payout') || str.includes('withdrawal')) {
                            return 'STATE: ' + JSON.stringify(state).substring(0, 2000);
                        }
                    }
                    
                    fiber = fiber.return;
                }
            }
        }
        return null;
    }
    
    const root = document.getElementById('__next') || document.getElementById('root');
    if (!root) return 'No root found';
    
    const result = findReactData(root);
    return result || 'No payout data in React fiber';
})()
"""))

# Navigate back
js("window.location.href = 'https://myfundedfutures.com/billing'")

ws.close()
print("\nDone.")
