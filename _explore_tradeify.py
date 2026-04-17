"""Explore Tradeify dashboard via CDP"""
import json, websocket, sys

PORT = 9222
TARGET_URL = "tradeify"

# Find the Tradeify tab
import urllib.request
tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=5).read())
tab = next((t for t in tabs if TARGET_URL in t.get('url', '').lower() and t['type'] == 'page'), None)
if not tab:
    print("ERROR: Tradeify tab not found")
    sys.exit(1)

print(f"Tab: {tab['title']} | {tab['url']}")
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

# 1. Page info
print("\n=== PAGE INFO ===")
info = evaluate('JSON.stringify({url: location.href, title: document.title})')
print(info)

# 2. Navigation / menu items
print("\n=== NAV / MENU ===")
nav = evaluate('''
JSON.stringify([...document.querySelectorAll('nav a, [role=menuitem], .sidebar a, .nav-link, [class*=menu] a, [class*=sidebar] a, [class*=nav] a')].map(e => ({
    text: e.textContent.trim().substring(0,60),
    href: e.href || e.getAttribute('href') || '',
    cls: (e.className || '').substring(0,60)
})).filter(e => e.text).slice(0, 30))
''')
print(nav)

# 3. Page headers and key data
print("\n=== HEADERS & KEY DATA ===")
headers = evaluate('''
JSON.stringify([...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(e => ({
    tag: e.tagName,
    text: e.textContent.trim().substring(0,120)
})).slice(0, 20))
''')
print(headers)

# 4. Tables
print("\n=== TABLES ===")
tables = evaluate('''
JSON.stringify([...document.querySelectorAll('table')].map((t, i) => ({
    index: i,
    rows: t.rows.length,
    headers: [...(t.querySelector('thead tr')?.cells || [])].map(c => c.textContent.trim()).join(' | '),
    firstRow: t.rows.length > 1 ? [...t.rows[1].cells].map(c => c.textContent.trim().substring(0,40)).join(' | ') : 'no data rows'
})))
''')
print(tables)

# 5. Cards / stat blocks
print("\n=== CARDS / STATS ===")
cards = evaluate('''
JSON.stringify([...document.querySelectorAll('[class*=card],[class*=stat],[class*=metric],[class*=account],[class*=balance],[class*=summary]')].map(e => ({
    cls: (e.className || '').substring(0,80),
    text: e.textContent.trim().substring(0,200)
})).slice(0, 20))
''')
print(cards)

# 6. Check for React/Angular/Vue
print("\n=== FRAMEWORK ===")
fw = evaluate('''
JSON.stringify({
    react: !!document.querySelector('[data-reactroot]') || !!window.__REACT_DEVTOOLS_GLOBAL_HOOK__,
    angular: !!window.ng || !!document.querySelector('[ng-version]'),
    vue: !!window.__VUE__,
    next: !!window.__NEXT_DATA__,
    nuxt: !!window.__NUXT__
})
''')
print(fw)

# 7. Cookies/tokens (names only, not values)
print("\n=== AUTH TOKENS ===")
tokens = evaluate('''
JSON.stringify({
    cookies: document.cookie.split(';').map(c => c.trim().split('=')[0]).filter(Boolean),
    localStorage_keys: Object.keys(localStorage).slice(0, 30),
    sessionStorage_keys: Object.keys(sessionStorage).slice(0, 20)
})
''')
print(tokens)

# 8. Network - check for API base URLs in the page source
print("\n=== API HINTS ===")
api = evaluate('''
JSON.stringify({
    fetch_base: (document.body?.innerHTML?.match(/https?:\\/\\/[^"'\\s]*api[^"'\\s]*/gi) || []).slice(0,10),
    XHR_base: (document.head?.innerHTML?.match(/https?:\\/\\/[^"'\\s]*api[^"'\\s]*/gi) || []).slice(0,10)
})
''')
print(api)

# 9. Get full body text summary (account info)
print("\n=== VISIBLE ACCOUNT DATA ===")
acct = evaluate('''
// Look for account numbers, balances, statuses
const body = document.body.innerText;
const lines = body.split('\\n').filter(l => l.trim()).slice(0, 80);
JSON.stringify(lines);
''')
print(acct)

ws.close()
print("\nDone.")
