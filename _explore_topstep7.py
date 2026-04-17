"""TopStep - try both user IDs, check billing page content properly, try normalizedPurchases."""
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

def gql_compact(label, query):
    """GraphQL query that strips the verbose extensions/explain from response."""
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
            const json = await resp.json();
            // Strip extensions to keep output clean
            delete json.extensions;
            return resp.status + ' | ' + JSON.stringify(json).substring(0, 8000);
        }})()
    """)
    print(result)

# Profile has id:93279 and userId:93348 - try both
for uid in [93348, 93279]:
    gql_compact(f"ACCOUNTS (userId={uid})", f"""{{
      accounts(condition: {{ userId: {uid} }}, orderBy: CREATED_AT_DESC, first: 20) {{
        nodes {{ rowId accountName stage status active startDate closedAt platformId createdAt }}
      }}
    }}""")
    
    gql_compact(f"PURCHASES (userId={uid})", f"""{{
      purchaseOrders(condition: {{ userId: {uid} }}, orderBy: CREATED_AT_DESC, first: 20) {{
        nodes {{ rowId type subtotal discount tax total paymentMethod processor createdAt }}
      }}
    }}""")
    
    gql_compact(f"CARD_TX (userId={uid})", f"""{{
      cardTransactions(condition: {{ userId: {uid} }}, orderBy: CREATED_AT_DESC, first: 20) {{
        nodes {{ rowId amount tax total type result ccCardNumber description createdAt }}
      }}
    }}""")

    gql_compact(f"SUBSCRIPTIONS (userId={uid})", f"""{{
      userSubscriptions(condition: {{ userId: {uid} }}, first: 20) {{
        nodes {{ rowId amount tax total active rebillDate isDunning createdAt }}
      }}
    }}""")

    gql_compact(f"PAYOUTS (userId={uid})", f"""{{
      payoutRequests(condition: {{ userId: {uid} }}, orderBy: CREATED_AT_DESC, first: 20) {{
        nodes {{ rowId accountId status amount requestedAmount method paid createdAt finalizedAt }}
      }}
    }}""")

# Try normalizedPurchasesByUser with lowercase userid
gql_compact("NORMALIZED_PURCHASES_93348", """{ normalizedPurchasesByUser(userid: 93348, first: 20) { nodes { displayDate displayType displayOrderId displayProduct displayPaymentMethod displaySubtotal displayDiscount displayTax displayTotal } } }""")

gql_compact("NORMALIZED_PURCHASES_93279", """{ normalizedPurchasesByUser(userid: 93279, first: 20) { nodes { displayDate displayType displayOrderId displayProduct displayPaymentMethod displaySubtotal displayDiscount displayTax displayTotal } } }""")

# Try normalizedSubsByUser
gql_compact("NORMALIZED_SUBS_93348", """{ normalizedSubsByUser(userid: 93348, first: 20) { nodes { displayDate displayProduct displayAmount displayStatus displayPaymentMethod } } }""")

# Navigate to billing page and wait for full render
print("\n=== NAVIGATING TO BILLING ===")
js("window.location.href = 'https://dashboard.topstep.com/dashboard/profile/billing'")
time.sleep(6)

# Get all text including table data
print("\n=== BILLING PAGE FULL TEXT ===")
text = js("document.body.innerText.substring(0, 6000)")
print(text)

# Check for table elements
print("\n=== BILLING TABLES ===")
tables = js("""
(() => {
    const tables = document.querySelectorAll('table');
    let result = 'Found ' + tables.length + ' tables\\n';
    tables.forEach((t, i) => {
        result += 'Table ' + i + ': ' + t.outerHTML.substring(0, 2000) + '\\n---\\n';
    });
    // Also check for MUI/Ant table patterns
    const muiTables = document.querySelectorAll('[class*="Table"], [class*="table"], [role="table"], [role="grid"]');
    result += '\\nMUI/grid elements: ' + muiTables.length;
    muiTables.forEach((t, i) => {
        result += '\\n  [' + i + '] ' + t.className.substring(0, 100) + ' | ' + (t.innerText || '').substring(0, 500);
    });
    return result;
})()
""")
print(tables)

# Navigate back
js("window.location.href = 'https://dashboard.topstep.com/dashboard/default?variant=new'")

ws.close()
print("\nDone.")
