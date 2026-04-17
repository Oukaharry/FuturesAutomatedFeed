"""Test: fetch min equity from all connected Tradovate accounts via existing Chrome sessions."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json

def api_fetch(driver, endpoint, method="GET", body=None):
    body_js = f"opts.body = JSON.stringify({json.dumps(body)});" if body else ""
    js = f"""
    var cb = arguments[arguments.length - 1];
    (async function() {{
        try {{
            var auth = JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{{}}');
            var token = auth.token || '';
            var env = auth.environment || 'demo';
            var base = 'https://' + env + '.tradovateapi.com/v1';
            var opts = {{
                method: '{method}',
                headers: {{
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }}
            }};
            {body_js}
            var r = await fetch(base + '{endpoint}', opts);
            var txt = await r.text();
            var d = null;
            try {{ d = JSON.parse(txt); }} catch(e) {{}}
            cb({{ok: r.ok, status: r.status, data: d}});
        }} catch(e) {{
            cb({{ok: false, error: e.toString()}});
        }}
    }})();
    """
    result = driver.execute_async_script(js)
    if result and result.get('ok'):
        return result.get('data')
    print(f"  FAILED: {result}")
    return None

# Find all running Chrome debugger ports by checking common ports
# The app uses ports starting from 9222
found = []
for port in range(9222, 9240):
    try:
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        driver = webdriver.Chrome(options=opts)
        url = driver.current_url
        if "tradovate" in url.lower() or "trader" in url.lower():
            found.append((port, driver))
            print(f"\n{'='*60}")
            print(f"Port {port}: {url}")
        else:
            print(f"Port {port}: Not Tradovate ({url[:60]})")
    except Exception as e:
        pass  # Port not in use

if not found:
    print("No Tradovate Chrome sessions found on ports 9222-9239")
    sys.exit(1)

for port, driver in found:
    print(f"\n--- Testing API on port {port} ---")
    
    # 1. Get accounts
    accounts = api_fetch(driver, "/account/list")
    if not accounts:
        print("  Could not fetch account list")
        continue
    
    for acct in accounts:
        aid = acct['id']
        name = acct.get('name', '?')
        print(f"\n  Account: {name} (id={aid})")
        
        # 2. Cash balance snapshot
        snapshot = api_fetch(driver, "/cashBalance/getCashBalanceSnapshot", "POST", {"accountId": aid})
        if snapshot:
            print(f"    netLiq:          ${snapshot.get('netLiq', 0):,.2f}")
            print(f"    cashBalance:     ${snapshot.get('cashBalance', 0):,.2f}")
            print(f"    realizedPnL:     ${snapshot.get('realizedPnL', 0):,.2f}")
            print(f"    unrealizedPnL:   ${snapshot.get('unrealizedPnL', 0):,.2f}")
        else:
            print("    Could not fetch cash balance snapshot")
        
        # 3. Auto-liq settings (drawdown limits)
        all_autoliq = api_fetch(driver, "/userAccountAutoLiq/list")
        if all_autoliq:
            al = None
            for entry in all_autoliq:
                if entry.get('accountId', entry.get('account')) == aid:
                    al = entry
                    break
            if al:
                print(f"    --- Auto Liquidation Settings ---")
                for key in sorted(al.keys()):
                    print(f"    {key}: {al[key]}")
                
                tmd = al.get('trailingMaxDrawdown', 0)
                tmdl = al.get('trailingMaxDrawdownLimit', 0)
                net_liq = snapshot.get('netLiq', 0) if snapshot else 0
                
                if tmdl > 0:
                    min_eq = tmdl
                elif tmd > 0:
                    min_eq = net_liq - tmd
                else:
                    min_eq = 0
                
                print(f"\n    >>> MIN EQUITY = ${min_eq:,.2f}")
                print(f"    >>> DRAWDOWN REMAINING = ${net_liq - min_eq:,.2f}")
            else:
                print("    No auto-liq entry found for this account")
        else:
            print("    Could not fetch auto-liq list")

print(f"\n{'='*60}")
print("Test complete.")
