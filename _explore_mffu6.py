"""Search MFFU Next.js chunks for payout/withdrawal API endpoint names."""
import sys, io, json, requests, websocket
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

# Get the build manifest to find payouts page chunk
print("=== PAYOUTS PAGE CHUNKS ===")
build_id = js("window.__NEXT_DATA__?.buildId || ''")
print(f"Build ID: {build_id}")

# Get the payouts page JS chunks
print(js("""
(async () => {
    // Get all chunks loaded for payouts page from build manifest
    const manifest = self.__BUILD_MANIFEST;
    if (!manifest) return 'No manifest';
    const payoutChunks = manifest['/payouts'] || [];
    return 'Payout chunks: ' + JSON.stringify(payoutChunks);
})()
"""))

# Navigate to payouts first to ensure its chunks are loaded
print("\n=== NAVIGATING TO PAYOUTS ===")
js("window.location.href = 'https://myfundedfutures.com/payouts'")
import time; time.sleep(4)

# Now search all loaded scripts for payout/withdrawal API patterns
print("\n=== SEARCHING ALL SCRIPTS FOR PAYOUT API ===")
print(js("""
(async () => {
    const scripts = Array.from(document.querySelectorAll('script[src*="_next"]'));
    let matches = [];
    for (const script of scripts) {
        try {
            const resp = await fetch(script.src);
            const text = await resp.text();
            
            // Search for payout-related API URLs
            const patterns = [
                /["']\/api\/[^"']*payout[^"']*/gi,
                /["']\/api\/[^"']*withdraw[^"']*/gi,
                /["'][^"']*api[^"']*payout[^"']*/gi,
                /["'][^"']*payout[^"']*api[^"']*/gi,
                /getPayouts|getUserPayouts|payout_requests|withdrawal/gi,
                /["']\/api\/get[A-Z][^"']*/gi,
            ];
            
            for (const p of patterns) {
                const found = text.match(p);
                if (found) {
                    matches.push(script.src.split('/').pop() + ': ' + [...new Set(found)].join(', '));
                }
            }
        } catch(e) {}
    }
    return matches.join('\\n') || '(nothing found in inline scripts)';
})()
"""))

# Also search ALL inline scripts
print("\n=== SEARCHING INLINE SCRIPTS ===")
print(js("""
(() => {
    const scripts = Array.from(document.querySelectorAll('script:not([src])'));
    let matches = [];
    for (const script of scripts) {
        const text = script.textContent || '';
        const patterns = [
            /["'][^"']*payout[^"']*/gi,
            /["'][^"']*withdraw[^"']*/gi,
        ];
        for (const p of patterns) {
            const found = text.match(p);
            if (found) {
                matches.push('[inline] ' + [...new Set(found)].slice(0, 5).join(', '));
            }
        }
    }
    return matches.join('\\n') || '(none)';
})()
"""))

# Let's look specifically at the payouts page JS chunk
print("\n=== FETCHING PAYOUTS JS CHUNK ===")
print(js("""
(async () => {
    const manifest = self.__BUILD_MANIFEST;
    if (!manifest) return 'No manifest';
    const payoutChunks = manifest['/payouts'] || [];
    const buildId = window.__NEXT_DATA__?.buildId;
    
    let apiRefs = [];
    for (const chunk of payoutChunks) {
        if (!chunk.endsWith('.js')) continue;
        try {
            const url = '/_next/static/' + chunk; 
            const resp = await fetch(url);
            const text = await resp.text();
            
            // Find all /api/ references
            const apiMatches = text.match(/["']\\/api\\/[^"']+["']/gi) || [];
            const fetchMatches = text.match(/fetch\\([^)]+/gi) || [];
            const axiosMatches = text.match(/\\.(get|post|put|delete)\\([^)]+/gi) || [];
            
            apiRefs.push(chunk + ' APIs: ' + [...new Set(apiMatches)].join(', '));
            if (fetchMatches.length) apiRefs.push(chunk + ' fetches: ' + fetchMatches.slice(0, 10).join(' | '));
            if (axiosMatches.length) apiRefs.push(chunk + ' axios: ' + axiosMatches.slice(0, 10).join(' | '));
        } catch(e) {
            apiRefs.push(chunk + ': ' + e.message);
        }
    }
    return apiRefs.join('\\n') || '(no chunks found)';
})()
"""))

# Try the WebSocket approach - get WS token and check WS messages
print("\n=== WS TOKEN ===")
print(js("""
(async () => {
    const resp = await fetch('https://api.myfundedfutures.com/api/getWSToken/', { credentials: 'include' });
    const data = await resp.json();
    return JSON.stringify(data);
})()
"""))

# Let's try finding the API by searching the webpack chunks directly
print("\n=== SEARCHING WEBPACK CHUNKS FOR API PATTERNS ===")
print(js("""
(async () => {
    // Get all loaded script URLs
    const entries = performance.getEntriesByType('resource').filter(e => e.name.includes('_next/static/chunks'));
    const results = [];
    
    for (const entry of entries) {
        try {
            const resp = await fetch(entry.name);
            const text = await resp.text();
            
            // Search for API endpoint definitions
            const apiPaths = text.match(/["']\\/api\\/[a-zA-Z_-]+\\/?["']/g) || [];
            if (apiPaths.length > 0) {
                const unique = [...new Set(apiPaths)];
                const name = entry.name.split('/').pop();
                results.push(name + ': ' + unique.join(', '));
            }
        } catch(e) {}
    }
    return results.join('\\n') || '(no api paths found)';
})()
"""))

# Navigate back to billing
js("window.location.href = 'https://myfundedfutures.com/billing'")

ws.close()
print("\nDone.")
