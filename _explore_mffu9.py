"""Call MFFU payout endpoints + account detail endpoints."""
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

def api_get(label, path):
    print(f"\n=== {label} ===")
    result = js(f"""
        (async () => {{
            const resp = await fetch('https://api.myfundedfutures.com/api/{path}', {{ credentials: 'include' }});
            const text = await resp.text();
            return resp.status + ' | ' + text.replace(/[\\u200b]/g, '').substring(0, 8000);
        }})()
    """)
    print(result)

# Payout endpoints
api_get("USER PAYOUTS PAGE", "getUserPayoutsPage/")
api_get("PAST PAYOUTS (page 1)", "getPastPayouts/?page=0&page_size=50")
api_get("PAST PAYOUTS (page 2)", "getPastPayouts/?page=1&page_size=50")

# Try getting account detail for one specific account
api_get("ACCOUNT DETAIL", "user-prop-accounts/b30d87ec-a5ea-4a4c-a2b9-2ea5ae1e9524/")

# Look for more endpoints in the accounts chunk
print("\n=== SEARCHING ACCOUNTS CHUNK ===")
print(js("""
(async () => {
    const entries = performance.getEntriesByType('resource')
        .filter(e => e.name.includes('_next/static/chunks') && e.name.endsWith('.js'));
    
    const results = [];
    for (const entry of entries) {
        try {
            const resp = await fetch(entry.name);
            const text = await resp.text();
            
            // Search for all URL strings used with the d.j() helper
            const urlPattern = /url:"([^"]+)"/gi;
            let m;
            const urls = new Set();
            while ((m = urlPattern.exec(text)) !== null) {
                urls.add(m[1]);
            }
            if (urls.size > 0) {
                const name = entry.name.split('/').pop();
                results.push(name + ': ' + [...urls].join(', '));
            }
        } catch(e) {}
    }
    return results.join('\\n') || '(none)';
})()
"""))

# Try stats/leaderboard/personal-settings endpoints from chunks
api_get("USER OVERVIEW", "getUserOverview/")
api_get("GET SETTINGS", "getSettings/")
api_get("PERSONAL SETTINGS", "getPersonalSettings/")
api_get("AFFILIATE INFO", "getAffiliateInfo/")

# Auth/token check  
print("\n=== AUTH MECHANISM ===")
print(js("""
(() => {
    // Check for auth cookies
    const cookies = document.cookie.split(';').map(c => c.trim().split('=')[0]);
    return 'Cookies: ' + cookies.join(', ');
})()
"""))

# Check headers used in API calls by examining the d.j helper
print("\n=== API HELPER FUNCTION ===")
print(js("""
(async () => {
    // Search for the API helper function definition
    const entries = performance.getEntriesByType('resource')
        .filter(e => e.name.includes('_next/static/chunks') && e.name.endsWith('.js'));
    
    for (const entry of entries) {
        try {
            const resp = await fetch(entry.name);
            const text = await resp.text();
            
            // Look for the secure API function
            const idx = text.indexOf('secure:');
            if (idx > -1) {
                const context = text.substring(Math.max(0, idx - 500), idx + 500);
                if (context.includes('Authorization') || context.includes('credentials') || context.includes('cookie') || context.includes('token')) {
                    return entry.name.split('/').pop() + ': ' + context.replace(/\\n/g, ' ').substring(0, 1000);
                }
            }
        } catch(e) {}
    }
    return '(not found)';
})()
"""))

ws.close()
print("\nDone.")
