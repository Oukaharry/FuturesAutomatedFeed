"""
TopStep X - Explore APIs via CDP (Chrome DevTools Protocol).
Launch Chrome with: --remote-debugging-port=9222
Log into https://dashboard.topstep.com first, then run this script.
"""
import json, requests, websocket, time, sys

PORT = 9222

# ── Find TopStep tab ──
tabs = requests.get(f"http://127.0.0.1:{PORT}/json").json()
topstep_tab = None
for t in tabs:
    url = t.get("url", "")
    if t.get("type") == "page" and "topstep" in url.lower():
        topstep_tab = t
        print(f"Found: {t.get('title','?')[:60]} | {url[:100]}")
        break

if not topstep_tab:
    print("No TopStep tab found. Available tabs:")
    for t in tabs:
        print(f"  [{t.get('type')}] {t.get('title','?')[:60]} | {t.get('url','')[:80]}")
    sys.exit(1)

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

# ── Helper: run fetch() inside the page context ──
def api_get(label, url):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  GET {url}")
    print(f"{'='*60}")
    result = js(f"""
        (async () => {{
            try {{
                const resp = await fetch('{url}', {{ credentials: 'include' }});
                const text = await resp.text();
                let parsed;
                try {{ parsed = JSON.parse(text); }} catch(e) {{ parsed = text; }}
                return JSON.stringify({{ status: resp.status, data: parsed }}).substring(0, 12000);
            }} catch(e) {{
                return JSON.stringify({{ error: e.message }});
            }}
        }})()
    """)
    try:
        obj = json.loads(result)
        print(f"Status: {obj.get('status', 'N/A')}")
        print(json.dumps(obj.get('data', obj), indent=2)[:6000])
    except:
        print(result[:6000])

def gql(label, query, variables=None):
    print(f"\n{'='*60}")
    print(f"  GQL: {label}")
    print(f"{'='*60}")
    body = {"query": query}
    if variables:
        body["variables"] = variables
    body_str = json.dumps(body).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    result = js(f"""
        (async () => {{
            try {{
                const profileResp = await fetch('https://api.topstep.com/me/profile/', {{ credentials: 'include' }});
                const profileData = await profileResp.json();
                const token = profileData.token;
                const resp = await fetch('https://crystal.topstep.com/graphql/q', {{
                    method: 'POST',
                    headers: {{ 
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token
                    }},
                    body: '{body_str}'
                }});
                const j = await resp.json();
                delete j.extensions;
                return JSON.stringify({{ status: resp.status, data: j }}).substring(0, 12000);
            }} catch(e) {{
                return JSON.stringify({{ error: e.message }});
            }}
        }})()
    """)
    try:
        obj = json.loads(result)
        print(f"Status: {obj.get('status', 'N/A')}")
        print(json.dumps(obj.get('data', obj), indent=2)[:6000])
    except:
        print(result[:6000])

# ═══════════════════════════════════════════════════════════
# 1) Profile / Identity
# ═══════════════════════════════════════════════════════════
api_get("PROFILE", "https://api.topstep.com/me/profile/")

# ═══════════════════════════════════════════════════════════
# 2) Accounts
# ═══════════════════════════════════════════════════════════
api_get("ACCOUNTS (basic)", "https://api.topstep.com/me/accounts/basic?offset=0&limit=50&sortBy=createdAt&sortOrder=desc")
api_get("ACCOUNTS (full)", "https://api.topstep.com/me/accounts/?offset=0&limit=50&sortBy=createdAt&sortOrder=desc")

# ═══════════════════════════════════════════════════════════
# 3) Account stats / trading data
# ═══════════════════════════════════════════════════════════
# Get the account IDs first
print("\n\n>>> Extracting account IDs...")
acct_data = js("""
    (async () => {
        const resp = await fetch('https://api.topstep.com/me/accounts/basic?offset=0&limit=50&sortBy=createdAt&sortOrder=desc', { credentials: 'include' });
        const j = await resp.json();
        if (j.data && Array.isArray(j.data)) {
            return JSON.stringify(j.data.map(a => ({id: a.id, name: a.name, status: a.status, type: a.type, phase: a.phase})));
        }
        return JSON.stringify(j).substring(0, 4000);
    })()
""")
print(f"Accounts: {acct_data[:3000]}")

# Parse account IDs for deeper probing
acct_ids = []
try:
    accts = json.loads(acct_data)
    if isinstance(accts, list):
        acct_ids = [a['id'] for a in accts if 'id' in a]
        print(f"Found {len(acct_ids)} account IDs: {acct_ids[:10]}")
except:
    pass

# Probe per-account endpoints
if acct_ids:
    aid = acct_ids[0]  # Use first account
    print(f"\n>>> Probing account {aid} endpoints...")
    
    api_get(f"ACCOUNT {aid} DETAILS", f"https://api.topstep.com/me/accounts/{aid}")
    api_get(f"ACCOUNT {aid} STATS", f"https://api.topstep.com/me/accounts/{aid}/stats")
    api_get(f"ACCOUNT {aid} STATISTICS", f"https://api.topstep.com/me/accounts/{aid}/statistics")
    api_get(f"ACCOUNT {aid} TRADING-STATS", f"https://api.topstep.com/me/accounts/{aid}/trading-stats")
    api_get(f"ACCOUNT {aid} POSITIONS", f"https://api.topstep.com/me/accounts/{aid}/positions")
    api_get(f"ACCOUNT {aid} ORDERS", f"https://api.topstep.com/me/accounts/{aid}/orders")
    api_get(f"ACCOUNT {aid} TRADES", f"https://api.topstep.com/me/accounts/{aid}/trades")
    api_get(f"ACCOUNT {aid} DAILY", f"https://api.topstep.com/me/accounts/{aid}/daily")
    api_get(f"ACCOUNT {aid} DAILY-STATS", f"https://api.topstep.com/me/accounts/{aid}/daily-stats")
    api_get(f"ACCOUNT {aid} PERFORMANCE", f"https://api.topstep.com/me/accounts/{aid}/performance")
    api_get(f"ACCOUNT {aid} DRAWDOWN", f"https://api.topstep.com/me/accounts/{aid}/drawdown")
    api_get(f"ACCOUNT {aid} BALANCE", f"https://api.topstep.com/me/accounts/{aid}/balance")
    api_get(f"ACCOUNT {aid} RULES", f"https://api.topstep.com/me/accounts/{aid}/rules")
    api_get(f"ACCOUNT {aid} CONFIG", f"https://api.topstep.com/me/accounts/{aid}/config")

# ═══════════════════════════════════════════════════════════
# 4) Billing / Payments
# ═══════════════════════════════════════════════════════════
api_get("BILLING V2 - FAILED REBILLS", "https://api.topstep.com/me/billing-v2/failedRebills")
api_get("BILLING V2 - INVOICES", "https://api.topstep.com/me/billing-v2/invoices")
api_get("BILLING V2 - PAYMENTS", "https://api.topstep.com/me/billing-v2/payments")
api_get("BILLING V2 - SUBSCRIPTIONS", "https://api.topstep.com/me/billing-v2/subscriptions")
api_get("BILLING V2 - CARDS", "https://api.topstep.com/me/billing-v2/cards")
api_get("BILLING", "https://api.topstep.com/me/billing/")
api_get("BILLING HISTORY", "https://api.topstep.com/me/billing/history")

# ═══════════════════════════════════════════════════════════
# 5) GraphQL - Account & billing data
# ═══════════════════════════════════════════════════════════
# Get user ID for GraphQL queries
print("\n\n>>> Getting user ID for GraphQL...")
user_id_raw = js("""
    (async () => {
        const resp = await fetch('https://api.topstep.com/me/profile/', { credentials: 'include' });
        const j = await resp.json();
        return String(j.id || j.userId || j.data?.id || '');
    })()
""")
print(f"User ID: {user_id_raw}")

try:
    user_id = int(user_id_raw)
except:
    user_id = None

if user_id:
    gql("PURCHASES", f"""{{ normalizedPurchasesByUser(userid: {user_id}, first: 50) {{ 
        nodes {{ id source type amount discount tax subtotal total method gateway 
                 paymentStatus fulfillmentStatus accountId accountName platform platformName createdAt }} 
    }} }}""")

    gql("SUBSCRIPTIONS", f"""{{ normalizedSubsDetailedByUser(userid: {user_id}, first: 50) {{ 
        nodes {{ id source productName productPrice amount tax total couponCode 
                 associatedAccountId associatedAccountName serviceAccessUntil 
                 subscriptionCancelledAt createdAt updatedAt }} 
    }} }}""")

    gql("SAVED CARDS", f"""{{ normalizedSavedCardsByUser(userid: {user_id}, first: 50) {{ 
        nodes {{ id source maskedCardNumber expirationMonth expirationYear defaultCard active }} 
    }} }}""")

# ═══════════════════════════════════════════════════════════
# 6) Payouts
# ═══════════════════════════════════════════════════════════
api_get("PAYOUTS", "https://api.topstep.com/me/payouts/")
api_get("PAYOUTS V2", "https://api.topstep.com/me/payouts-v2/")
api_get("WITHDRAWAL", "https://api.topstep.com/me/withdrawal/")
api_get("WITHDRAWALS", "https://api.topstep.com/me/withdrawals/")

# ═══════════════════════════════════════════════════════════
# 7) Misc endpoints
# ═══════════════════════════════════════════════════════════
api_get("NOTIFICATIONS", "https://api.topstep.com/me/notifications/")
api_get("CHALLENGES", "https://api.topstep.com/me/challenges/")
api_get("PRODUCTS", "https://api.topstep.com/products/")
api_get("COUPONS", "https://api.topstep.com/me/coupons/")

# ═══════════════════════════════════════════════════════════
# 8) Intercept XHR on dashboard pages to discover more APIs
# ═══════════════════════════════════════════════════════════
print("\n\n>>> Installing network interceptor and navigating to dashboard...")
js("""
    window.__captured_requests = [];
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        if (url.includes('api.topstep') || url.includes('graphql') || url.includes('crystal')) {
            window.__captured_requests.push({type: 'fetch', url: url, time: Date.now()});
        }
        return origFetch.apply(this, args);
    };
    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        if (url && (url.includes('api.topstep') || url.includes('graphql') || url.includes('crystal'))) {
            window.__captured_requests.push({type: 'xhr', method: method, url: url, time: Date.now()});
        }
        return origOpen.apply(this, [method, url, ...rest]);
    };
""")

# Navigate through key pages to trigger API calls
pages = [
    ("dashboard", "https://dashboard.topstep.com/dashboard"),
    ("accounts", "https://dashboard.topstep.com/dashboard/accounts"),
    ("profile", "https://dashboard.topstep.com/dashboard/profile"),
    ("billing", "https://dashboard.topstep.com/dashboard/profile/billing"),
]

for name, url in pages:
    print(f"\n>>> Navigating to {name}...")
    js(f"window.location.href = '{url}'")
    time.sleep(4)
    current = js("window.location.href")
    print(f"  URL: {current}")

# Dump captured requests
print("\n" + "="*60)
print("  ALL CAPTURED API REQUESTS")
print("="*60)
captured = js("JSON.stringify(window.__captured_requests || [])")
try:
    reqs = json.loads(captured)
    seen = set()
    for r in reqs:
        key = f"{r.get('method','GET')} {r.get('url','')}"
        if key not in seen:
            seen.add(key)
            print(f"  [{r.get('type')}] {r.get('method','GET')} {r.get('url','')}")
    print(f"\nTotal unique API calls: {len(seen)}")
except:
    print(captured[:4000])

ws.close()
print("\n\nDone.")
