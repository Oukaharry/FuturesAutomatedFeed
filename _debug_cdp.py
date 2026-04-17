#!/usr/bin/env python3
"""Debug CDP connectivity issues."""
import json, urllib.request, websocket, time

data = urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()
tabs = json.loads(data)
print("All page tabs:")
for t in tabs:
    if t.get('type') == 'page':
        print(f"  {t['id'][:20]} | {t['url'][:60]}")
        print(f"    ws: {t.get('webSocketDebuggerUrl','NONE')[:80]}")

tf = next((t for t in tabs if 'tradeify' in t.get('url', '')), None)
if not tf:
    print("No Tradeify tab found")
    exit(1)

# Try activating the target first via /json/activate
target_id = tf['id']
print(f"\nActivating target {target_id}...")
try:
    resp = urllib.request.urlopen(f'http://127.0.0.1:9222/json/activate/{target_id}', timeout=5).read()
    print(f"Activate response: {resp}")
except Exception as e:
    print(f"Activate failed: {e}")

# Re-fetch tabs to get fresh WS URL
time.sleep(0.5)
data2 = urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()
tabs2 = json.loads(data2)
tf2 = next((t for t in tabs2 if t['id'] == target_id), None)
ws_url = tf2['webSocketDebuggerUrl'] if tf2 else tf['webSocketDebuggerUrl']
print(f"WS URL: {ws_url}")

# Connect
ws = websocket.create_connection(ws_url, timeout=10)
print(f"Connected: {ws.connected}")

# Send eval directly (Runtime.evaluate doesn't require Runtime.enable)
ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 
                     'params': {'expression': 'document.title', 'returnByValue': True}}))

ws.settimeout(10)
for i in range(20):
    try:
        raw = ws.recv()
        d = json.loads(raw)
        print(f"  msg#{i}: id={d.get('id')} method={d.get('method','')} err={d.get('error',{}).get('message','')}")
        if d.get('id') == 1:
            print(f"  RESULT: {d.get('result',{}).get('result',{}).get('value','<none>')}")
            break
    except websocket.WebSocketTimeoutException:
        print(f"  msg#{i}: TIMEOUT after 10s - no response received")
        break

ws.close()
print("Done")
