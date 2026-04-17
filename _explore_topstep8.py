"""TopStep - introspect NormalizedPurchase type, wait longer for billing page."""
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

def gql(label, query):
    print(f"\n=== {label} ===")
    q = json.dumps({"query": query})
    q_escaped = q.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    result = js(f"""
        (async () => {{
            const profileResp = await fetch('https://api.topstep.com/me/profile/', {{ credentials: 'include' }});
            const profileData = await profileResp.json();
            const token = profileData.token;
            const resp = await fetch('https://crystal.topstep.com/graphql/q', {{
                method: 'POST',
                headers: {{ 
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                }},
                body: '{q_escaped}'
            }});
            const j = await resp.json();
            delete j.extensions;
            return resp.status + ' | ' + JSON.stringify(j).substring(0, 8000);
        }})()
    """)
    print(result)

# Introspect the normalized types
gql("NormalizedPurchasesByUserRecord FIELDS", """{ __type(name: "NormalizedPurchasesByUserRecord") { fields { name type { name kind } } } }""")
gql("NormalizedSubsByUserRecord FIELDS", """{ __type(name: "NormalizedSubsByUserRecord") { fields { name type { name kind } } } }""")
gql("NormalizedSubsDetailedByUserRecord FIELDS", """{ __type(name: "NormalizedSubsDetailedByUserRecord") { fields { name type { name kind } } } }""")
gql("NormalizedSavedCardsByUserRecord FIELDS", """{ __type(name: "NormalizedSavedCardsByUserRecord") { fields { name type { name kind } } } }""")

# Now query with correct fields (subtotal, discount suggested by error)
gql("NORMALIZED_PURCHASES", """{ normalizedPurchasesByUser(userid: 93348, first: 50) { nodes { subtotal discount } } }""")
gql("NORMALIZED_PURCHASES_2", """{ normalizedPurchasesByUser(userid: 93279, first: 50) { nodes { subtotal discount } } }""")

# Try purchases query - the "purchases" root field (different from purchaseOrders)
gql("PURCHASES_ROOT", """{ purchases(userid: 93348, first: 50) { nodes { subtotal discount } } }""")

# Navigate to billing
print("\n=== NAVIGATING TO BILLING ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/profile/billing'")
time.sleep(8)

# Check URL
url = js("window.location.href")
print(f"URL: {url}")

# Full DOM dump
print("\n=== FULL DOM TEXT ===")
text = js("document.body.innerText.substring(0, 8000)")
print(text if text else "(EMPTY)")

# Check if there are any loading spinners still
print("\n=== LOADING STATE ===")
loading = js("""
(() => {
    const spinners = document.querySelectorAll('[class*="spinner"], [class*="Spinner"], [class*="loading"], [class*="Loading"], [class*="skeleton"], [class*="Skeleton"], [role="progressbar"]');
    let result = 'Spinners/loaders: ' + spinners.length + '\\n';
    // Check if page has actual rendered content
    const root = document.getElementById('root');
    if (root) {
        result += 'Root children: ' + root.children.length + '\\n';
        result += 'Root innerHTML length: ' + root.innerHTML.length + '\\n';
        result += 'Root innerText length: ' + (root.innerText || '').length + '\\n';
    }
    // Check for React error boundaries
    const errors = document.querySelectorAll('[class*="error"], [class*="Error"]');
    errors.forEach(e => {
        result += 'Error element: ' + (e.innerText || '').substring(0, 200) + '\\n';
    });
    return result;
})()
""")
print(loading)

# Check network requests made on billing page
print("\n=== BILLING PAGE NETWORK REQUESTS ===")
net = js("""
(() => {
    const entries = performance.getEntriesByType('resource');
    const apis = entries.filter(e => 
        (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
        (e.name.includes('api.topstep.com') || e.name.includes('crystal.topstep.com'))
    );
    const seen = new Set();
    return apis.filter(e => {
        const u = new URL(e.name);
        const key = u.origin + u.pathname;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).map(e => '[' + e.initiatorType + '] ' + e.name).join('\\n') || '(none)';
})()
""")
print(net)

# Navigate back
js("window.location.href = 'https://dashboard.topstep.com/dashboard/default?variant=new'")

ws.close()
print("\nDone.")
