"""Debug: Connect to Chrome debug port and explore Tradovate API for min equity."""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json, sys

PORT = 52416

opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{PORT}")
print(f"Connecting to Chrome on port {PORT}...")
driver = webdriver.Chrome(options=opts)
print(f"URL: {driver.current_url}")

def api_fetch(endpoint, method="GET", body=None):
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
            cb({{ok: r.ok, status: r.status, data: d, raw: txt.substring(0, 500)}});
        }} catch(e) {{
            cb({{ok: false, error: e.toString()}});
        }}
    }})();
    """
    result = driver.execute_async_script(js)
    return result

# 1. Get accounts
print("\n=== /account/list ===")
r = api_fetch("/account/list")
if not r.get('ok'):
    print(f"FAILED: {r}")
    sys.exit(1)
accounts = r['data']
for acct in accounts:
    print(f"  id={acct['id']}  name={acct.get('name','?')}  active={acct.get('active')}")

aid = accounts[0]['id']
aname = accounts[0].get('name', '?')
print(f"\nUsing account: {aname} (id={aid})")

# 2. Cash balance snapshot
print("\n=== /cashBalance/getCashBalanceSnapshot ===")
r = api_fetch("/cashBalance/getCashBalanceSnapshot", "POST", {"accountId": aid})
if r.get('ok'):
    d = r['data']
    for k in sorted(d.keys()):
        print(f"  {k}: {d[k]}")
else:
    print(f"  FAILED: {r}")

# 3. Auto-liq settings  
print("\n=== /userAccountAutoLiq/list ===")
r = api_fetch("/userAccountAutoLiq/list")
if r.get('ok'):
    for entry in r['data']:
        if entry.get('accountId', entry.get('account')) == aid:
            print(f"  --- Entry for account {aid} ---")
            for k in sorted(entry.keys()):
                print(f"    {k}: {entry[k]}")
        else:
            print(f"  (skipped entry for account {entry.get('accountId', entry.get('account', '?'))})")
else:
    print(f"  FAILED: {r}")

# 4. Try /userAccountRiskParameter/list
print("\n=== /userAccountRiskParameter/list ===")
r = api_fetch("/userAccountRiskParameter/list")
if r.get('ok'):
    for entry in r['data']:
        if entry.get('accountId', entry.get('account')) == aid:
            print(f"  --- Entry for account {aid} ---")
            for k in sorted(entry.keys()):
                print(f"    {k}: {entry[k]}")
else:
    print(f"  FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

# 5. Try /account/item?id=
print(f"\n=== /account/item?id={aid} ===")
r = api_fetch(f"/account/item?id={aid}")
if r.get('ok'):
    d = r['data']
    for k in sorted(d.keys()):
        print(f"  {k}: {d[k]}")
else:
    print(f"  FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

# 6. Try /userAccountPositionLimit/list
print("\n=== /userAccountPositionLimit/list ===")
r = api_fetch("/userAccountPositionLimit/list")
if r.get('ok'):
    for entry in (r['data'] or []):
        print(f"  {entry}")
else:
    print(f"  FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

# 7. Try /marginSnapshot/list  
print(f"\n=== /marginSnapshot/list ===")
r = api_fetch("/marginSnapshot/list")
if r.get('ok'):
    for entry in (r['data'] or []):
        if entry.get('accountId', entry.get('account')) == aid:
            for k in sorted(entry.keys()):
                print(f"    {k}: {entry[k]}")
else:
    print(f"  FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

# 8. Try the account/find endpoint for more details
print(f"\n=== /account/find?name={aname} ===")
r = api_fetch(f"/account/find?name={aname}")
if r.get('ok'):
    d = r['data']
    for k in sorted(d.keys()):
        print(f"  {k}: {d[k]}")
else:
    print(f"  FAILED: status={r.get('status')}")

print("\n=== DONE ===")
