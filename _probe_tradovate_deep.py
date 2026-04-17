"""Deep analysis of Tradovate auth flow and API endpoints from main.js."""
import requests
import re

MAIN_JS = "https://cdn.tradovate.com/tradovate/scripts/main.ecd7d06c.js"
r = requests.get(MAIN_JS, timeout=15)
js = r.text

# 1. Find the OAuth/SSO flow
print("=== OAUTH / SSO FLOW ===")
for keyword in ["exchangeShortGrantCode", "oAuth", "/oauth", "ssoHost", "authorize", 
                "shortGrantCode", "code:", "appId"]:
    idx = 0
    count = 0
    while True:
        idx = js.find(keyword, idx)
        if idx < 0 or count >= 3:
            break
        context = js[max(0, idx-150):idx+150]
        print(f"\n  '{keyword}' at {idx}:")
        print(f"    {context}")
        idx += len(keyword)
        count += 1

# 2. Find REST API method patterns
print("\n\n=== REST API METHODS ===")
# The Tradovate API uses patterns like restApi().getXXX() or restApi().postXXX()
rest_methods = re.findall(r'restApi\(\)\.\w+', js)
print(f"  Found {len(set(rest_methods))} unique restApi methods:")
for m in sorted(set(rest_methods)):
    print(f"    {m}")

# 3. Find entity/model names (these correspond to API entities)
print("\n\n=== API ENTITY PATTERNS ===")
# Look for patterns like EntityType.FILL, EntityType.ORDER etc.
entity_patterns = re.findall(r'(?:EntityType|entityType|ENTITY_TYPE)[\.\[]+["\']?(\w+)', js)
for e in sorted(set(entity_patterns)):
    print(f"  {e}")

# 4. Look for the URL builder that constructs API paths
print("\n\n=== URL CONSTRUCTION PATTERNS ===")
# Find patterns like: `/v1/` + something
v1_patterns = re.findall(r'["`\']/?v1/([^"`\']+)["`\']', js)
for p in sorted(set(v1_patterns)):
    if len(p) < 80:
        print(f"  /v1/{p}")

# 5. Find WebSocket message types (these show what data can be streamed)
print("\n\n=== WEBSOCKET MESSAGE TYPES ===")
ws_types = re.findall(r'["\'](?:subscribe|unsubscribe|md/|user/|auth/|heartbeat|replay/)[^"\']*["\']', js)
for t in sorted(set(ws_types)):
    print(f"  {t}")

# 6. Look around "Account Reports" page to find what API it calls
print("\n\n=== ACCOUNT REPORTS PAGE ANALYSIS ===")
idx = js.find("Account Reports")
if idx >= 0:
    # Get a big chunk around it
    chunk = js[max(0, idx-2000):idx+3000]
    # Find fetch/API calls in that chunk
    api_calls = re.findall(r'(?:fetch|get|post|restApi)\([^)]*["\'][^"\']+["\']', chunk)
    for call in api_calls:
        print(f"  {call}")
    
    # Find any URL patterns
    urls = re.findall(r'["\']([^"\']*(?:/v1/|api|report|fill|balance|history|pnl)[^"\']*)["\']', chunk, re.I)
    for u in sorted(set(urls)):
        if len(u) < 100:
            print(f"  URL: {u}")

# 7. Find the P&L History component
print("\n\n=== P&L HISTORY COMPONENT ===")
for keyword in ["P&L History", "pnlHistory", "PnlHistory", "dailyPnl", "DailyPnl"]:
    idx = js.find(keyword)
    if idx >= 0:
        chunk = js[max(0, idx-1500):idx+1500]
        api_calls = re.findall(r'["\']([^"\']*(?:pnl|fill|balance|report|history|account)[^"\']*)["\']', chunk, re.I)
        print(f"  Near '{keyword}':")
        for call in sorted(set(api_calls)):
            if len(call) < 100 and not call.endswith('css'):
                print(f"    {call}")

# 8. Find all fetch() or XMLHttpRequest patterns
print("\n\n=== FETCH/XHR PATTERNS ===")
# Modern apps use fetch()
fetch_patterns = re.findall(r'fetch\(["`\']([^"`\']+)["`\']', js)
print(f"  fetch() calls ({len(set(fetch_patterns))}):")
for f in sorted(set(fetch_patterns)):
    if len(f) < 100:
        print(f"    {f}")

# Also look for axios or other HTTP libraries
http_patterns = re.findall(r'(?:axios|http)\.\w+\(["`\']([^"`\']+)["`\']', js)
if http_patterns:
    print(f"\n  HTTP library calls ({len(set(http_patterns))}):")
    for h in sorted(set(http_patterns)):
        print(f"    {h}")
