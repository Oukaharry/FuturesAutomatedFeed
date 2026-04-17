"""TopStep - fix GraphQL auth, search JS bundles for API routes."""
import json, requests, websocket, time

tabs = requests.get("http://127.0.0.1:9222/json").json()
topstep_tab = next(t for t in tabs if t.get("type") == "page" and "topstep" in t.get("url", "").lower() and "login" not in t.get("url", "").lower())
ws = websocket.create_connection(topstep_tab["webSocketDebuggerUrl"], timeout=60)
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

# 1) Get the token from the profile response
print("=== GET AUTH TOKEN ===")
token = js("""
    (async () => {
        const resp = await fetch('https://api.topstep.com/me/profile/', { credentials: 'include' });
        const data = await resp.json();
        return data.token;
    })()
""")
print(f"Token: {token[:50]}...")

# 2) Try GraphQL with Bearer token
print("\n=== GRAPHQL WITH TOKEN - INTROSPECTION (short) ===")
result = js("""
    (async () => {
        const profileResp = await fetch('https://api.topstep.com/me/profile/', { credentials: 'include' });
        const profileData = await profileResp.json();
        const token = profileData.token;
        
        const resp = await fetch('https://crystal.topstep.com/graphql/introspect', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({
                query: '{ __schema { queryType { name fields { name } } mutationType { name fields { name } } } }'
            })
        });
        const text = await resp.text();
        return resp.status + ' | ' + text.substring(0, 5000);
    })()
""")
print(result)

# 3) Try crystal.topstep.com with credentials: include too
print("\n=== GRAPHQL WITH CREDENTIALS INCLUDE ===")
result = js("""
    (async () => {
        const resp = await fetch('https://crystal.topstep.com/graphql/schema', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: '{ __schema { queryType { name fields { name } } } }'
            })
        });
        const text = await resp.text();
        return resp.status + ' | ' + text.substring(0, 5000);
    })()
""")
print(result)

# 4) Search JS bundles for API endpoints
print("\n=== JS BUNDLE API ROUTES ===")
routes = js("""
(() => {
    const scripts = performance.getEntriesByType('resource').filter(e => e.initiatorType === 'script');
    return scripts.map(s => s.name).join('\\n');
})()
""")
print(routes)

# 5) Search main chunk for API patterns
print("\n=== SEARCHING JS FOR API PATTERNS ===")
result = js("""
    (async () => {
        const scripts = performance.getEntriesByType('resource').filter(e => e.initiatorType === 'script' && e.name.includes('chunk'));
        const results = [];
        for (const s of scripts.slice(0, 3)) {
            try {
                const resp = await fetch(s.name);
                const text = await resp.text();
                // Find API patterns
                const apiPatterns = text.match(/["']\\/me\\/[^"']+["']/g) || [];
                const gqlPatterns = text.match(/["']crystal[^"']*["']/g) || [];
                const apiTopstep = text.match(/api\\.topstep\\.com[^"'\\s]*/g) || [];
                const crystalUrls = text.match(/crystal\\.topstep\\.com[^"'\\s]*/g) || [];
                if (apiPatterns.length || gqlPatterns.length || apiTopstep.length || crystalUrls.length) {
                    results.push(s.name.split('/').pop() + ':\\n  /me/ routes: ' + [...new Set(apiPatterns)].join(', ') + 
                                '\\n  crystal: ' + [...new Set(crystalUrls)].join(', ') +
                                '\\n  api.topstep: ' + [...new Set(apiTopstep)].join(', '));
                }
            } catch(e) { results.push(s.name.split('/').pop() + ': ERROR ' + e.message); }
        }
        return results.join('\\n\\n') || '(none found)';
    })()
""")
print(result)

# 6) Also check the main JS files (not just chunks)
print("\n=== SEARCHING ALL JS FOR API ROUTES ===")
result = js("""
    (async () => {
        const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
        const results = [];
        for (const src of scripts.slice(0, 5)) {
            try {
                const resp = await fetch(src);
                const text = await resp.text();
                const meRoutes = text.match(/["']\\/me\\/[a-zA-Z0-9\\/-]+["']/g) || [];
                const accounts = text.match(/accounts\\/[a-z-]+/g) || [];
                const combined = [...new Set([...meRoutes, ...accounts])];
                if (combined.length) {
                    results.push(src.split('/').pop().substring(0, 40) + ':\\n  ' + combined.join('\\n  '));
                }
            } catch(e) {}
        }
        return results.join('\\n\\n') || '(none found)';
    })()
""")
print(result)

# 7) Also try GET on accounts with more specific params
print("\n=== ACCOUNTS WITH STATUS FILTER ===")
for status in ['active', 'combine', 'funded', 'expired', 'all']:
    result = js(f"""
        (async () => {{
            const resp = await fetch('https://api.topstep.com/me/accounts/basic?offset=0&limit=50&sortBy=createdAt&sortOrder=desc&status={status}', {{
                credentials: 'include'
            }});
            const text = await resp.text();
            return '{status}: ' + resp.status + ' | ' + text.substring(0, 300);
        }})()
    """)
    print(result)

ws.close()
print("\nDone.")
