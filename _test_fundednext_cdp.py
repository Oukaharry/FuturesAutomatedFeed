"""Quick test to verify Chrome DevTools Protocol and grab FundedNext page content"""
import time
import json
import urllib.request
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9222

print(f"Waiting 5s for Chrome to settle...")
time.sleep(5)

print(f"Connecting to Chrome DevTools on port {PORT}...")
try:
    data = urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=5).read()
    tabs = json.loads(data)
    print(f"Found {len(tabs)} tabs/workers")
    
    fn_tab = None
    for t in tabs:
        if t.get('type') == 'page':
            print(f"  Page: {t['title']} -> {t['url'][:100]}")
            if 'fundednext' in t.get('url', ''):
                fn_tab = t
    
    if not fn_tab:
        print("\nFundedNext accounts tab not found. Please navigate to https://app.fundednext.com/accounts")
        sys.exit(1)
    
    print(f"\nConnecting to FundedNext tab via WebSocket...")
    import websocket
    ws = websocket.create_connection(fn_tab['webSocketDebuggerUrl'], timeout=10)
    
    # Get page text content
    js = 'document.body.innerText.substring(0, 8000)'
    ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
    result = json.loads(ws.recv())
    body_text = result.get('result', {}).get('result', {}).get('value', 'NO DATA')
    
    # Get dollar values
    js2 = '(document.body.innerText.match(/-?\\$[\\d,]+\\.?\\d*/g) || []).join("\\n")'
    ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': js2, 'returnByValue': True}}))
    result2 = json.loads(ws.recv())
    dollars = result2.get('result', {}).get('result', {}).get('value', '')
    
    # Get HTML structure of main content area
    js3 = '''
    (() => {
        const cards = document.querySelectorAll('[class*="card"], [class*="Card"], [class*="account"], [class*="Account"]');
        const results = [];
        cards.forEach((c, i) => {
            if(c.innerText.trim().length > 20) {
                results.push({index: i, tag: c.tagName, classes: c.className.substring(0, 200), text: c.innerText.substring(0, 600)});
            }
        });
        return JSON.stringify(results.slice(0, 15));
    })()
    '''
    ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 'params': {'expression': js3, 'returnByValue': True}}))
    result3 = json.loads(ws.recv())
    cards_json = result3.get('result', {}).get('result', {}).get('value', '[]')
    cards = json.loads(cards_json)
    
    ws.close()
    
    print(f"\n{'='*60}")
    print(f"PAGE: {fn_tab['title']} - {fn_tab['url']}")
    print(f"{'='*60}")
    
    print(f"\n--- Dollar Values Found ---")
    print(dollars if dollars else "(none)")
    
    print(f"\n--- Cards/Account Elements ({len(cards)}) ---")
    for c in cards:
        print(f"\nCard {c['index']} ({c['tag']}, classes={c['classes'][:80]}):")
        print(c['text'][:400])
    
    print(f"\n--- Full Page Text ---")
    print(body_text[:5000])
    
except urllib.error.URLError as e:
    print(f"Cannot connect to Chrome on port {PORT}: {e}")
    print(f"Make sure Chrome is running with: --remote-debugging-port={PORT}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
