"""Use CDP to intercept the ACTUAL auth call the Tradovate web trader makes."""
import json
import requests
import websocket
import time

CDP_PORT = 9222

def get_tradovate_tabs():
    """Find all Tradovate-related tabs in Chrome debug."""
    try:
        r = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=5)
        tabs = r.json()
        trado_tabs = [t for t in tabs if "tradovate" in t.get("url", "").lower()]
        return trado_tabs
    except:
        return []

def cdp_eval(ws_url, expression, timeout=10):
    """Evaluate JS in a Chrome tab via CDP."""
    ws = websocket.create_connection(ws_url, timeout=timeout)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": expression, "returnByValue": True, "awaitPromise": True
    }}))
    result = json.loads(ws.recv())
    ws.close()
    return result

# First check if Chrome debug is running
tabs = get_tradovate_tabs()
print(f"Found {len(tabs)} Tradovate tab(s) in CDP Chrome:")
for t in tabs:
    print(f"  - {t['title'][:60]} | {t['url'][:80]}")

if tabs:
    tab = tabs[0]
    ws_url = tab["webSocketDebuggerUrl"]
    print(f"\nConnecting to: {tab['title']}")
    
    # Extract ALL storage tokens
    print("\n=== sessionStorage ===")
    result = cdp_eval(ws_url, """
        (function() {
            var items = {};
            for (var i = 0; i < sessionStorage.length; i++) {
                var key = sessionStorage.key(i);
                var val = sessionStorage.getItem(key);
                // Truncate long values
                items[key] = val.length > 200 ? val.substring(0, 200) + '...' : val;
            }
            return JSON.stringify(items);
        })()
    """)
    val = result.get("result", {}).get("result", {}).get("value", "{}")
    storage = json.loads(val)
    for k, v in storage.items():
        print(f"  {k}: {v[:120]}")
    
    # Check localStorage too
    print("\n=== localStorage ===")
    result = cdp_eval(ws_url, """
        (function() {
            var items = {};
            for (var i = 0; i < localStorage.length; i++) {
                var key = localStorage.key(i);
                var val = localStorage.getItem(key);
                items[key] = val.length > 200 ? val.substring(0, 200) + '...' : val;
            }
            return JSON.stringify(items);
        })()
    """)
    val = result.get("result", {}).get("result", {}).get("value", "{}")
    storage = json.loads(val)
    for k, v in storage.items():
        print(f"  {k}: {v[:120]}")
    
    # Try to extract the token from the app's state
    print("\n=== Looking for auth tokens in window/app state ===")
    token_searches = [
        "window.__STORE__ && JSON.stringify(Object.keys(window.__STORE__))",
        "window.__NEXT_DATA__ && JSON.stringify(Object.keys(window.__NEXT_DATA__))",
        "document.cookie",
        # The Tradovate web app stores token in specific places
        "sessionStorage.getItem('tradovate-api-access-token') || sessionStorage.getItem('access_token') || 'NOT_FOUND'",
        # Search for any key containing 'token'
        """(function() {
            var tokens = {};
            for (var i = 0; i < sessionStorage.length; i++) {
                var key = sessionStorage.key(i);
                if (key.toLowerCase().includes('token') || key.toLowerCase().includes('auth') || key.toLowerCase().includes('access')) {
                    tokens[key] = sessionStorage.getItem(key);
                }
            }
            for (var i = 0; i < localStorage.length; i++) {
                var key = localStorage.key(i);
                if (key.toLowerCase().includes('token') || key.toLowerCase().includes('auth') || key.toLowerCase().includes('access')) {
                    tokens[key] = localStorage.getItem(key);
                }
            }
            return JSON.stringify(tokens);
        })()""",
    ]
    
    for expr in token_searches:
        result = cdp_eval(ws_url, expr)
        val = result.get("result", {}).get("result", {}).get("value", "N/A")
        print(f"\n  {expr[:60]}...")
        print(f"  -> {str(val)[:200]}")

    # Intercept network requests to find the actual API calls
    print("\n\n=== Intercepting network requests ===")
    ws = websocket.create_connection(ws_url, timeout=15)
    
    # Enable network monitoring
    ws.send(json.dumps({"id": 10, "method": "Network.enable", "params": {}}))
    ws.recv()  # ack
    
    # Collect requests for a few seconds
    print("  Monitoring for 5 seconds...")
    api_calls = []
    start = time.time()
    ws.settimeout(1)
    while time.time() - start < 5:
        try:
            msg = json.loads(ws.recv())
            method = msg.get("method", "")
            if method == "Network.requestWillBeSent":
                url = msg["params"]["request"]["url"]
                req_method = msg["params"]["request"]["method"]
                headers = msg["params"]["request"].get("headers", {})
                if "tradovate" in url.lower() or "api" in url.lower():
                    auth_header = headers.get("Authorization", "")
                    api_calls.append({
                        "method": req_method,
                        "url": url,
                        "has_auth": bool(auth_header),
                        "auth": auth_header[:50] if auth_header else ""
                    })
        except:
            pass
    
    ws.close()
    
    if api_calls:
        print(f"\n  Captured {len(api_calls)} API calls:")
        seen = set()
        for call in api_calls:
            key = f"{call['method']} {call['url']}"
            if key not in seen:
                seen.add(key)
                auth_info = f" [AUTH: {call['auth']}]" if call['has_auth'] else ""
                print(f"    {call['method']} {call['url'][:100]}{auth_info}")
    else:
        print("  No API calls captured (page may be idle)")

else:
    print("\nNo Tradovate tabs found in CDP Chrome (port 9222).")
    print("The Tradovate instances are likely in Selenium-launched Chrome processes.")
    print("\nAlternative: Let's try to extract tokens from the Selenium drivers in the running trader app.")
    
    # Try connecting to trader app's Selenium instances
    # Check if there are any chrome processes with debug ports
    import subprocess
    result = subprocess.run(["powershell", "-c", 
        "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object Id, CommandLine | Format-List"],
        capture_output=True, text=True)
    print("\nChrome processes:")
    print(result.stdout[:2000] if result.stdout else "None found")
