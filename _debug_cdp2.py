#!/usr/bin/env python3
"""Debug API responses for each firm."""
import json, urllib.request, websocket, time

def connect_tab(domain, port=9222):
    data = urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=5).read()
    tabs = json.loads(data)
    tab = next((t for t in tabs if domain in t.get('url', '') and t.get('type') == 'page'), None)
    if not tab:
        return None, None
    tid = tab.get('id', '')
    try: urllib.request.urlopen(f'http://127.0.0.1:{port}/json/activate/{tid}', timeout=5)
    except: pass
    ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30)
    return ws, tab['url']

def cdp_eval(ws, expr, await_p=False):
    msg = {'id': 1, 'method': 'Runtime.evaluate', 
           'params': {'expression': expr, 'returnByValue': True}}
    if await_p:
        msg['params']['awaitPromise'] = True
    ws.send(json.dumps(msg))
    ws.settimeout(15)
    while True:
        try:
            r = json.loads(ws.recv())
            if r.get('id') == 1:
                return r.get('result', {}).get('result', {}).get('value')
        except websocket.WebSocketTimeoutException:
            return None

def fetch(ws, url, method='GET', body=None):
    if body is not None:
        js = f"""(async () => {{
            const r = await fetch({json.dumps(url)}, {{
                method: '{method}', credentials: 'include',
                headers: {{'Content-Type': 'application/json'}},
                body: {json.dumps(json.dumps(body))}
            }});
            return JSON.stringify({{s: r.status, b: await r.text()}});
        }})()"""
    else:
        js = f"""(async () => {{
            const r = await fetch({json.dumps(url)}, {{credentials: 'include'}});
            return JSON.stringify({{s: r.status, b: await r.text()}});
        }})()"""
    raw = cdp_eval(ws, js, True)
    if raw:
        d = json.loads(raw)
        return d.get('s'), d.get('b', '')[:2000]
    return None, None

print("="*60)
print("TRADEIFY")
print("="*60)
ws, url = connect_tab('tradeify')
if ws:
    s, b = fetch(ws, 'https://app-f.tradeify.co/api/auth/profile/')
    print(f"Profile [{s}]: {b[:500]}")
    s, b = fetch(ws, 'https://app-f.tradeify.co/api/dashboard/broker-credentials')
    print(f"\nBroker Creds [{s}]: {b[:500]}")
    s, b = fetch(ws, 'https://app-f.tradeify.co/api/dashboard/get-subscription-list?page=1&page_size=100')
    print(f"\nSubscriptions [{s}]: {b[:500]}")
    ws.close()

print("\n" + "="*60)
print("LUCID")
print("="*60)
ws, url = connect_tab('lucidtrading')
if ws:
    token = cdp_eval(ws, "localStorage.getItem('auth_token')")
    print(f"Token: {str(token)[:50]}...")
    # Try all common localStorage keys
    all_keys = cdp_eval(ws, """(() => {
        const items = {};
        for (let i=0; i<localStorage.length; i++) {
            const k = localStorage.key(i);
            items[k] = (localStorage.getItem(k)||'').substring(0,100);
        }
        return JSON.stringify(items);
    })()""")
    print(f"LocalStorage: {all_keys[:500]}")
    ws.close()

print("\n" + "="*60)
print("TOPSTEP")
print("="*60)
ws, url = connect_tab('topstep')
if ws:
    # Check token sources
    all_keys = cdp_eval(ws, """(() => {
        const items = {};
        for (let i=0; i<localStorage.length; i++) {
            const k = localStorage.key(i);
            items[k] = (localStorage.getItem(k)||'').substring(0,100);
        }
        return JSON.stringify(items);
    })()""")
    print(f"LocalStorage: {all_keys[:600]}")
    s, b = fetch(ws, 'https://api.topstep.com/me/profile/')
    print(f"\nProfile [{s}]: {b[:500]}")
    s, b = fetch(ws, 'https://api.topstep.com/me/accounts/basic?offset=0&limit=15&sortBy=createdAt&sortOrder=desc')
    print(f"\nAccounts [{s}]: {b[:500]}")
    ws.close()

print("\n" + "="*60)
print("MFFU")
print("="*60)
ws, url = connect_tab('myfundedfutures')
if ws:
    s, b = fetch(ws, 'https://api.myfundedfutures.com/api/getProfile/')
    print(f"Profile [{s}]: {b[:600]}")
    s, b = fetch(ws, 'https://api.myfundedfutures.com/api/user-prop-accounts/?page=1&page_size=5')
    print(f"\nAccounts [{s}]: {b[:600]}")
    # Test subscriptions with GET (not POST)
    s, b = fetch(ws, 'https://api.myfundedfutures.com/api/getSubscriptions/')
    print(f"\nSubscriptions GET [{s}]: {b[:300]}")
    # Test with POST, no body at all
    js = """(async () => {
        const r = await fetch('https://api.myfundedfutures.com/api/getSubscriptions/', {
            method: 'POST', credentials: 'include'
        });
        return JSON.stringify({s: r.status, b: await r.text()});
    })()"""
    raw = cdp_eval(ws, js, True)
    if raw:
        d = json.loads(raw)
        print(f"\nSubscriptions POST no-body [{d['s']}]: {d['b'][:300]}")
    ws.close()

print("\nDone")
