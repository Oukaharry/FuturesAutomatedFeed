import json, sys, time
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import TradeifyAccount

s = TradeifyAccount(debug_port=9222)
s.login()

# Install network interceptor
s._js("""
    (() => {
        window.__trRequests = [];
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0] ? args[0].url : 'unknown');
            window.__trRequests.push({type:'fetch', url, time: Date.now()});
            return origFetch.apply(this, args);
        };
        const origXHR = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            window.__trRequests.push({type:'xhr', method, url, time: Date.now()});
            return origXHR.call(this, method, url, ...rest);
        };
        return 'ok';
    })()
""")

# Check current page content
url = s._js("window.location.href")
print("Current URL:", url)

# Navigate to trigger fresh data loading
s._js("window.location.href = 'https://app-f.tradeify.co/'")
time.sleep(5)

# Get intercepted requests
reqs = s._js("JSON.stringify(window.__trRequests || [])")
if reqs:
    requests = json.loads(reqs)
    print(f"\n{len(requests)} intercepted requests:")
    for r in requests:
        u = r.get('url', '')
        if 'api' in u.lower() or 'tradeify' in u.lower() or 'graphql' in u.lower():
            print(f"  {r.get('type','?')} {r.get('method','GET')} {u}")

# Also check performance entries for API calls
entries = s._js("""
    (() => {
        const all = performance.getEntries().filter(e => 
            e.entryType === 'resource' && 
            (e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch') &&
            e.name.includes('api')
        );
        return JSON.stringify(all.map(e => ({name: e.name, type: e.initiatorType})));
    })()
""")
print("\nAPI performance entries:", entries)

# Check DOM for balance info
dom = s._js("""
    (() => {
        const body = document.body.innerText;
        return body.substring(0, 3000);
    })()
""")
print("\nPage content:")
print(dom[:2000] if dom else "No content")

s.close()
