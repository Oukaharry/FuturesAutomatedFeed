"""TopStep - call GraphQL queries for accounts, purchases, subscriptions."""
import json, requests, websocket

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

def gql(label, query, variables=None):
    print(f"\n=== {label} ===")
    q = json.dumps({"query": query, "variables": variables or {}})
    # Escape for JS string
    q_escaped = q.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    result = js(f"""
        (async () => {{
            const profileResp = await fetch('https://api.topstep.com/me/profile/', {{ credentials: 'include' }});
            const profileData = await profileResp.json();
            const token = profileData.token;
            const resp = await fetch('https://crystal.topstep.com/graphql/{label.replace(' ','_')}', {{
                method: 'POST',
                headers: {{ 
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                }},
                body: '{q_escaped}'
            }});
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 5000);
        }})()
    """)
    print(result)

# Get detailed schema for key types
gql("ACCOUNT_FIELDS", """
{ __type(name: "Account") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

gql("PURCHASE_ORDER_FIELDS", """
{ __type(name: "PurchaseOrder") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

gql("PAYOUT_REQUEST_FIELDS", """
{ __type(name: "PayoutRequest") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

gql("CARD_TRANSACTION_FIELDS", """
{ __type(name: "CardTransaction") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

gql("NORMALIZED_PURCHASE_FIELDS", """
{ __type(name: "NormalizedPurchase") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

gql("USER_SUBSCRIPTION_FIELDS", """
{ __type(name: "UserSubscription") { 
    fields { name type { name kind ofType { name kind } } }
}}""")

# Now query actual data
USER_ID = 93348  # from profile

gql("MY_ACCOUNTS", """
query { accounts(condition: { userId: 93348 }) { nodes {
    id userId status accountType balance profitTarget maxLoss startingBalance
    createdAt updatedAt
}}}""")

gql("MY_PURCHASES", f"""
query {{ purchaseOrders(condition: {{ userId: {USER_ID} }}) {{ nodes {{
    id userId status amount createdAt updatedAt
}}}}}}""")

gql("MY_NORMALIZED_PURCHASES", f"""
query {{ normalizedPurchasesByUser(userId: {USER_ID}) {{ nodes {{
    id userId amount status createdAt
}}}}}}""")

gql("MY_CARD_TRANSACTIONS", f"""
query {{ cardTransactions(condition: {{ userId: {USER_ID} }}) {{ nodes {{
    id userId amount status createdAt
}}}}}}""")

gql("MY_SUBSCRIPTIONS", f"""
query {{ userSubscriptions(condition: {{ userId: {USER_ID} }}) {{ nodes {{
    id userId status createdAt
}}}}}}""")

gql("MY_SAVED_CARDS", f"""
query {{ savedCards(condition: {{ userId: {USER_ID} }}) {{ nodes {{
    id userId lastFour brand createdAt
}}}}}}""")

# Also try the REST billing endpoint found in JS
print("\n=== REST: BILLING V2 FAILED REBILLS ===")
result = js("""
    (async () => {
        const resp = await fetch('https://api.topstep.com/me/billing-v2/failedRebills', { credentials: 'include' });
        const text = await resp.text();
        return resp.status + ' | ' + text.substring(0, 2000);
    })()
""")
print(result)

ws.close()
print("\nDone.")
