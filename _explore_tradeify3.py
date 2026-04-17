"""Explore Tradeify billing + account details via API"""
import json, websocket, time, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PORT = 9222
tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=5).read())
tab = next((t for t in tabs if 'tradeify' in t.get('url', '').lower() and t['type'] == 'page'), None)
if not tab: print("ERROR: Tradeify tab not found"); exit(1)

ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=15)
msg_id = 0

def send(method, params=None):
    global msg_id; msg_id += 1
    msg = {'id': msg_id, 'method': method}
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == msg_id: return resp

def evaluate(expr):
    r = send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
    return r.get('result', {}).get('result', {}).get('value')

# 1. Call key APIs directly from the browser context (uses existing auth cookies)
print("=== PROFILE API ===")
profile = evaluate('''
fetch('/api/auth/profile/').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(profile)

print("\n=== BROKER CREDENTIALS ===")
creds = evaluate('''
fetch('/api/dashboard/broker-credentials').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(creds)

print("\n=== ORDER LIST (purchases) ===")
orders = evaluate('''
fetch('/api/dashboard/get-order-list?page=1&page_size=20').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(orders)

print("\n=== SUBSCRIPTION LIST ===")
subs = evaluate('''
fetch('/api/dashboard/get-subscription-list?page=1&page_size=20').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(subs)

print("\n=== RESET ORDER LIST ===")
resets = evaluate('''
fetch('/api/dashboard/get-reset-order-list?page=1&page_size=20').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(resets)

print("\n=== PAYMENT METHODS ===")
payments = evaluate('''
fetch('/api/dashboard/payment-methods/payment-methods-list').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(payments)

print("\n=== PAYOUT TRACKING ===")
payouts = evaluate('''
fetch('/api/payouts/payout-tracking?page=1&page_size=20&start_date=2020-01-01&end_date=2026-12-31').then(r => r.json()).then(d => JSON.stringify(d, null, 2))
''')
print(payouts)

# 2. Get billing page visible content
print("\n=== BILLING PAGE TEXT ===")
evaluate("window.location.href = 'https://app-f.tradeify.co/billing'")
time.sleep(4)
billing_text = evaluate('document.body.innerText.substring(0, 4000)')
print(billing_text)

# 3. Navigate to accounts page and get account details
print("\n=== ACCOUNTS PAGE ===")
evaluate("window.location.href = 'https://app-f.tradeify.co/'")
time.sleep(4)
accts_text = evaluate('document.body.innerText.substring(0, 4000)')
print(accts_text)

# 4. Try to find all accounts API
print("\n=== ACCOUNTS API SEARCH ===")
# Try various common endpoints
for endpoint in ['/api/dashboard/accounts', '/api/accounts', '/api/dashboard/get-accounts', '/api/user/accounts']:
    result = evaluate(f"fetch('{endpoint}').then(r => r.status + ' ' + r.statusText).catch(e => 'error: ' + e.message)")
    print(f"  {endpoint} -> {result}")

ws.close()
print("\nDone.")
