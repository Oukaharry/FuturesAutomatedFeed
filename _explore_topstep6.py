"""TopStep - correct GraphQL queries with proper field names from schema."""
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
    exc = r.get("result", {}).get("exceptionDetails")
    if exc:
        return f"JS ERROR: {exc.get('text', '')} {exc.get('exception', {}).get('description', '')}"
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
            const text = await resp.text();
            return resp.status + ' | ' + text.substring(0, 8000);
        }})()
    """)
    print(result)

USER_ID = 93348

# Accounts with correct fields from schema
gql("ACCOUNTS", f"""{{
  accounts(condition: {{ userId: {USER_ID} }}, orderBy: CREATED_AT_DESC) {{
    nodes {{
      rowId
      accountName
      accountTemplate
      stage
      status
      active
      startDate
      closedAt
      platformId
      subscriptionId
      productCategoryId
      complimentary
      createdAt
      updatedAt
    }}
  }}
}}""")

# Purchase orders with correct fields
gql("PURCHASE_ORDERS", f"""{{
  purchaseOrders(condition: {{ userId: {USER_ID} }}, orderBy: CREATED_AT_DESC) {{
    nodes {{
      rowId
      type
      subtotal
      discount
      tax
      total
      localCurrency
      paymentMethod
      processor
      gatewayTransactionId
      processorTransactionId
      invoiceTemplate
      couponSnapshot
      createdAt
      updatedAt
    }}
  }}
}}""")

# Card transactions with correct fields
gql("CARD_TRANSACTIONS", f"""{{
  cardTransactions(condition: {{ userId: {USER_ID} }}, orderBy: CREATED_AT_DESC) {{
    nodes {{
      rowId
      amount
      tax
      total
      type
      result
      errorDescription
      ccCardNumber
      ccExpMonth
      ccExpYear
      description
      gateway
      nuveiPaymentId
      stripePaymentId
      createdAt
    }}
  }}
}}""")

# Subscriptions with correct fields
gql("USER_SUBSCRIPTIONS", f"""{{
  userSubscriptions(condition: {{ userId: {USER_ID} }}) {{
    nodes {{
      rowId
      rebillDate
      amount
      tax
      total
      active
      isDunning
      dunningStartDate
      dunningAttempts
      lastRenewalDate
      originalProductPrice
      createdAt
      updatedAt
    }}
  }}
}}""")

# Payout requests
gql("PAYOUT_REQUESTS", f"""{{
  payoutRequests(condition: {{ userId: {USER_ID} }}, orderBy: CREATED_AT_DESC) {{
    nodes {{
      rowId
      accountId
      status
      amount
      requestedAmount
      method
      targetCurrency
      note
      paid
      finalizedAt
      createdAt
      updatedAt
    }}
  }}
}}""")

# Saved cards
gql("SAVED_CARDS", f"""{{
  savedCards(condition: {{ userId: {USER_ID} }}) {{
    nodes {{
      rowId
      createdAt
    }}
  }}
}}""")

# Normalized purchases (use lowercase userid)
gql("NORMALIZED_PURCHASES", f"""{{
  normalizedPurchasesByUser(userid: {USER_ID}) {{
    nodes {{ id }}
  }}
}}""")

# Also try the REST accounts endpoint with auth header
print("\n=== REST ACCOUNTS WITH AUTH ===")
result = js(f"""
    (async () => {{
        const profileResp = await fetch('https://api.topstep.com/me/profile/', {{ credentials: 'include' }});
        const profileData = await profileResp.json();
        const token = profileData.token;
        const resp = await fetch('https://api.topstep.com/me/accounts/basic?offset=0&limit=50&sortBy=createdAt&sortOrder=desc', {{
            credentials: 'include',
            headers: {{ 'Authorization': 'Bearer ' + token }}
        }});
        const text = await resp.text();
        return resp.status + ' | ' + text.substring(0, 5000);
    }})()
""")
print(result)

ws.close()
print("\nDone.")
