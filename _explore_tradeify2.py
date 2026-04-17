"""Deep explore Tradeify - API interception, account details, billing"""
import json, websocket, time, urllib.request

PORT = 9222
TARGET_URL = "tradeify"

tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=5).read())
tab = next((t for t in tabs if TARGET_URL in t.get('url', '').lower() and t['type'] == 'page'), None)
if not tab:
    print("ERROR: Tradeify tab not found"); exit(1)

ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=15)

msg_id = 0
def send(method, params=None):
    global msg_id
    msg_id += 1
    msg = {'id': msg_id, 'method': method}
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == msg_id:
            return resp

def evaluate(expr):
    r = send('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    return r.get('result', {}).get('result', {}).get('value')

# 1. Enable Network interception to capture API calls
print("=== ENABLING NETWORK MONITORING ===")
send('Network.enable')

# 2. Navigate to billing page to capture API
print("\n=== NAVIGATING TO BILLING ===")
evaluate("window.location.href = 'https://app-f.tradeify.co/billing'")
time.sleep(5)

# 3. Collect all network requests made
print("\n=== CAPTURING NETWORK REQUESTS ===")
# Read events for a few seconds
requests = []
ws.settimeout(3)
try:
    while True:
        msg = json.loads(ws.recv())
        if msg.get('method') == 'Network.requestWillBeSent':
            req = msg['params']['request']
            requests.append({'url': req['url'], 'method': req['method']})
        elif msg.get('method') == 'Network.responseReceived':
            resp = msg['params']['response']
            if 'api' in resp['url'].lower() or 'graphql' in resp['url'].lower():
                requests.append({'url': resp['url'], 'status': resp['status'], 'type': 'response'})
except:
    pass
ws.settimeout(15)

print(f"Captured {len(requests)} requests")
# Filter API calls
api_calls = [r for r in requests if any(kw in r['url'].lower() for kw in ['api', 'graphql', 'query', 'rest', '/v1/', '/v2/'])]
print(f"\nAPI Calls ({len(api_calls)}):")
for r in api_calls[:30]:
    print(f"  {r.get('method','?')} {r['url'][:150]}")

# 4. Get billing page content
print("\n=== BILLING PAGE CONTENT ===")
billing = evaluate('''
JSON.stringify({
    url: location.href,
    title: document.title,
    text: document.body.innerText.substring(0, 3000)
})
''')
print(billing)

# 5. Check for auth tokens in localStorage/cookies more deeply
print("\n=== AUTH DEEP CHECK ===")
auth = evaluate('''
(function() {
    const result = {};
    // Check all localStorage keys for tokens
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        const val = localStorage.getItem(key);
        if (val && (key.toLowerCase().includes('token') || key.toLowerCase().includes('auth') || key.toLowerCase().includes('user') || key.toLowerCase().includes('session'))) {
            result[key] = val.substring(0, 200);
        }
    }
    // Check cookies
    result._cookies = document.cookie;
    return JSON.stringify(result);
})()
''')
print(auth)

# 6. Try to find API base URL from JS bundles or window config
print("\n=== WINDOW CONFIG / API BASE ===")
config = evaluate('''
JSON.stringify({
    env: window.__ENV__ || window.ENV || null,
    config: window.__CONFIG__ || window.CONFIG || null,
    api: window.API_URL || window.API_BASE || window.__API__ || null,
    runtime: window.__RUNTIME_CONFIG__ || null,
    meta_env: (() => {
        try {
            const metas = document.querySelectorAll('meta[name*=api], meta[name*=base], meta[content*=api]');
            return [...metas].map(m => ({name: m.name, content: m.content}));
        } catch(e) { return []; }
    })()
})
''')
print(config)

# 7. Navigate back to accounts and get account details
print("\n=== NAVIGATING BACK TO ACCOUNTS ===")
evaluate("window.location.href = 'https://app-f.tradeify.co/'")
time.sleep(4)

# 8. Click "View details" to see full account info
print("\n=== ACCOUNT CARD DETAILS ===")
details = evaluate('''
(function() {
    // Get all account cards data
    const cards = document.querySelectorAll('[class*=accordion]');
    const accounts = [];
    cards.forEach(card => {
        const text = card.innerText;
        if (text.includes('Tradovate') || text.includes('Active') || text.includes('Failed') || text.includes('Funded')) {
            accounts.push(text.substring(0, 500));
        }
    });
    return JSON.stringify(accounts);
})()
''')
print(details)

# 9. Try to intercept XHR/fetch by overriding
print("\n=== INTERCEPTED API FROM PAGE LOAD ===")
performance = evaluate('''
JSON.stringify(
    performance.getEntriesByType('resource')
        .filter(e => e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch')
        .map(e => ({name: e.name, duration: Math.round(e.duration)}))
)
''')
print(performance)

ws.close()
print("\nDone.")
