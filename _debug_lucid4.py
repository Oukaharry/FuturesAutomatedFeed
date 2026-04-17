import json, sys, time
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import LucidTradingAccount

s = LucidTradingAccount(debug_port=9222)
s.login()

# Install interceptor
s._js("""
    (() => {
        window.__lucidRequests = [];
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0] ? args[0].url : 'unknown');
            window.__lucidRequests.push({type:'fetch', url, time: Date.now()});
            return origFetch.apply(this, args);
        };
        const origXHR = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            window.__lucidRequests.push({type:'xhr', method, url, time: Date.now()});
            return origXHR.call(this, method, url, ...rest);
        };
        return 'ok';
    })()
""")

# Navigate to trigger requests
s._js("window.location.hash = '#/startup'")
time.sleep(2)
s._js("window.location.hash = '#/account-summary'")
time.sleep(3)

reqs = s._js("JSON.stringify(window.__lucidRequests || [])")
print("Intercepted requests:")
if reqs:
    for r in json.loads(reqs):
        print(f"  {r}")

# Check for WebSocket connections
ws_check = s._js("""
    (() => {
        // Check if there's a websocket
        const ws = [];
        if (window.__lucidWS) ws.push('custom tracker');
        return JSON.stringify({wsFound: ws.length > 0});
    })()
""")
print("\nWebSocket check:", ws_check)

# Full DOM inspection of account-summary page
print("\n=== Full DOM content ===")
content = s._js("""
    (() => {
        const main = document.querySelector('main, .main-content, app-root, [role=main]');
        if (main) return main.innerText;
        return document.body.innerText.substring(0, 3000);
    })()
""")
print(content[:2000] if content else "No content")

# Check specific data elements
print("\n=== Specific data ===")
specific = s._js("""
    (() => {
        const data = {};
        // Account cards or similar
        const cards = document.querySelectorAll('.card, .account-card, mat-card, [class*=account]');
        data.cards = cards.length;
        // Table rows
        const rows = document.querySelectorAll('tr');
        data.tableRows = [];
        rows.forEach((r, i) => {
            if (i < 10) {
                const cells = [];
                r.querySelectorAll('td, th').forEach(c => cells.push(c.textContent.trim()));
                if (cells.length > 0) data.tableRows.push(cells);
            }
        });
        // Specific text content
        const allText = document.body.innerText;
        data.hasBalance = allText.includes('Balance') || allText.includes('balance');
        data.hasEquity = allText.includes('Equity') || allText.includes('equity');
        data.hasProfit = allText.includes('Profit') || allText.includes('P&L') || allText.includes('PnL');
        return JSON.stringify(data);
    })()
""")
print(specific)

s.close()
