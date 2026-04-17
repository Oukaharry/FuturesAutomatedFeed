"""Debug: More detailed API exploration for min equity."""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json, sys

PORT = 52416
opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{PORT}")
driver = webdriver.Chrome(options=opts)

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
            cb({{ok: r.ok, status: r.status, data: d, raw: txt.substring(0, 2000)}});
        }} catch(e) {{
            cb({{ok: false, error: e.toString()}});
        }}
    }})();
    """
    return driver.execute_async_script(js)

aid = 46645337

# 1. Dump ALL autoLiq entries raw
print("=== /userAccountAutoLiq/list (ALL entries raw) ===")
r = api_fetch("/userAccountAutoLiq/list")
if r.get('ok'):
    for i, entry in enumerate(r['data'] or []):
        print(f"\n  Entry {i}:")
        for k in sorted(entry.keys()):
            print(f"    {k}: {entry[k]}")
else:
    print(f"  FAILED: {r.get('raw','')[:300]}")

# 2. Check autoLiqProfile
print(f"\n=== /autoLiqProfile/item?id=43 ===")
r = api_fetch("/autoLiqProfile/item?id=43")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    for k in sorted(r['data'].keys()):
        print(f"    {k}: {r['data'][k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 3. Check riskCategory
print(f"\n=== /riskCategory/item?id=243 ===")
r = api_fetch("/riskCategory/item?id=243")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    for k in sorted(r['data'].keys()):
        print(f"    {k}: {r['data'][k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 4. Try /userAccountAutoLiq/find
print(f"\n=== /userAccountAutoLiq/find?accountId={aid} ===")
r = api_fetch(f"/userAccountAutoLiq/find?accountId={aid}")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    for k in sorted(r['data'].keys()):
        print(f"    {k}: {r['data'][k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 5. Try /userAccountAutoLiq/deps?masterid=
print(f"\n=== /userAccountAutoLiq/deps?masterid={aid} ===")
r = api_fetch(f"/userAccountAutoLiq/deps?masterid={aid}")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    if isinstance(r['data'], list):
        for entry in r['data']:
            for k in sorted(entry.keys()):
                print(f"    {k}: {entry[k]}")
    else:
        for k in sorted(r['data'].keys()):
            print(f"    {k}: {r['data'][k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 6. Try /userAccountAutoLiq/ldeps?masterids=
print(f"\n=== /userAccountAutoLiq/ldeps?masterids={aid} ===")
r = api_fetch(f"/userAccountAutoLiq/ldeps?masterids={aid}")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    if isinstance(r['data'], list):
        for entry in r['data']:
            for k in sorted(entry.keys()):
                print(f"    {k}: {entry[k]}")
    else:
        for k in sorted(r['data'].keys()):
            print(f"    {k}: {r['data'][k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 7. Try to get the Tradovate UI's own riskLimits or accountRiskStatus
print(f"\n=== /accountRiskStatus/list ===")
r = api_fetch("/accountRiskStatus/list")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    for entry in (r['data'] if isinstance(r['data'], list) else [r['data']]):
        for k in sorted(entry.keys()):
            print(f"    {k}: {entry[k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 8. Check user properties
print(f"\n=== /tradingPermission/list ===")
r = api_fetch("/tradingPermission/list")
print(f"  ok={r.get('ok')} status={r.get('status')}")
if r.get('ok') and r.get('data'):
    for entry in (r['data'] if isinstance(r['data'], list) else [r['data']]):
        for k in sorted(entry.keys()):
            print(f"    {k}: {entry[k]}")
else:
    print(f"  raw: {r.get('raw','')[:300]}")

# 9. Check if there's anything in session/local storage about risk
print(f"\n=== Browser localStorage/sessionStorage risk data ===")
js = """
var cb = arguments[arguments.length - 1];
var result = {};
for (var i = 0; i < sessionStorage.length; i++) {
    var key = sessionStorage.key(i);
    if (key.toLowerCase().indexOf('risk') >= 0 || key.toLowerCase().indexOf('liq') >= 0 || 
        key.toLowerCase().indexOf('drawdown') >= 0 || key.toLowerCase().indexOf('equity') >= 0) {
        result['session_' + key] = sessionStorage.getItem(key).substring(0, 500);
    }
}
for (var i = 0; i < localStorage.length; i++) {
    var key = localStorage.key(i);
    if (key.toLowerCase().indexOf('risk') >= 0 || key.toLowerCase().indexOf('liq') >= 0 ||
        key.toLowerCase().indexOf('drawdown') >= 0 || key.toLowerCase().indexOf('equity') >= 0) {
        result['local_' + key] = localStorage.getItem(key).substring(0, 500);
    }
}
cb(result);
"""
r = driver.execute_async_script(js)
for k in sorted(r.keys()):
    print(f"  {k}: {r[k]}")

print("\n=== DONE ===")
