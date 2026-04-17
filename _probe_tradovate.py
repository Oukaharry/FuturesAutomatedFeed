"""
Tradovate API Probe v2 — Same Chrome config as TradeOps AI but with images ON.
Opens browser for manual login, then extracts tokens and probes the full API.
"""
import json, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ── Chrome: EXACT same flags as TradovateAccount BUT with images ENABLED ──
opts = Options()
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-crash-reporter")
opts.add_argument("--disable-in-process-stack-traces")
opts.add_argument("--disable-logging")
opts.add_argument("--log-level=3")
opts.add_argument("--silent")
opts.add_argument("--disable-features=TranslateUI")
opts.add_argument("--disable-features=MediaRouter")
opts.add_argument("--disable-component-update")
opts.add_argument("--disable-background-timer-throttling")
opts.add_argument("--disable-backgrounding-occluded-windows")
opts.add_argument("--disable-renderer-backgrounding")
opts.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
opts.add_argument("--disable-extensions")
opts.add_argument("--disable-plugins")
# *** IMAGES ENABLED — no --disable-images, no --blink-settings=imagesEnabled=false ***
opts.add_argument("--disable-background-networking")
opts.add_argument("--disable-default-apps")
opts.add_argument("--disable-sync")
opts.add_argument("--window-size=1400,900")
opts.add_argument("--disable-software-rasterizer")
# Anti-detection (same as TradeOps AI)
opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
opts.add_experimental_option('useAutomationExtension', False)
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("prefs", {
    "profile.default_content_setting_values": {"popups": 2, "notifications": 2}
})

print("=" * 60)
print("  Tradovate API Probe — Images ON, manual login")
print("=" * 60)
driver = webdriver.Chrome(options=opts)
# Extra anti-detection: hide webdriver flag
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
})
driver.get("https://trader.tradovate.com/welcome")
print("\n✅ Chrome open at Tradovate login page")
print("👉 Log in MANUALLY (solve CAPTCHA if shown)")
print("👉 Select Simulation mode, wait for trading screen")
print("👉 Then press ENTER here\n")
input("Press ENTER after you see the trading dashboard... ")

# ── Extract storage ──────────────────────────────────────────
print("\n🔑 Extracting auth data from browser...")
storage = driver.execute_script("""
var r = {ss:{}, ls:{}, cookies: document.cookie, url: location.href};
for (var i=0; i<sessionStorage.length; i++) { var k=sessionStorage.key(i); r.ss[k]=sessionStorage.getItem(k); }
for (var i=0; i<localStorage.length; i++) { var k=localStorage.key(i); r.ls[k]=localStorage.getItem(k); }
return r;
""")

print(f"\n📦 URL: {storage['url']}")
print(f"\n── sessionStorage ({len(storage['ss'])} keys) ──")
for k, v in sorted(storage['ss'].items()):
    print(f"  {k}: {v[:200]}{'...' if len(v)>200 else ''}")
print(f"\n── localStorage ({len(storage['ls'])} keys) ──")
for k, v in sorted(storage['ls'].items()):
    print(f"  {k}: {v[:200]}{'...' if len(v)>200 else ''}")
print(f"\n── Cookies ──\n  {storage['cookies'][:400]}")

# ── Find token ───────────────────────────────────────────────
token = None
token_source = None

for sn, st in [('sessionStorage', storage['ss']), ('localStorage', storage['ls'])]:
    for key in ['access_token','token','accessToken','auth_token','jwt','mdAccessToken']:
        if key in st:
            token = st[key]; token_source = f"{sn}[{key}]"; break
    if token: break

if not token:
    for sn, st in [('sessionStorage', storage['ss']), ('localStorage', storage['ls'])]:
        for k, v in st.items():
            try:
                p = json.loads(v)
                if isinstance(p, dict):
                    for tk in ['accessToken','access_token','token','mdAccessToken']:
                        if tk in p and p[tk]:
                            token = p[tk]; token_source = f"{sn}[{k}].{tk}"; break
                if token: break
            except: pass
        if token: break

if token:
    print(f"\n✅ Token: {token_source}\n   {token[:80]}...")

# ── Network interceptors ─────────────────────────────────────
print("\n🌐 Installing network interceptors...")
driver.execute_script("""
window.__api=[];window.__wsu=[];window.__wsm=[];
if(!window.__p){
  var _f=window.fetch;
  window.fetch=function(){var u=arguments[0],o=arguments[1]||{};
    window.__api.push({url:typeof u==='string'?u:u.url,method:o.method||'GET',
      headers:JSON.stringify(o.headers||{}),body:typeof o.body==='string'?o.body.substring(0,500):null});
    return _f.apply(this,arguments);};
  var _xo=XMLHttpRequest.prototype.open,_xs=XMLHttpRequest.prototype.setRequestHeader,_xsn=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open=function(m,u){this._m=m;this._u=u;this._h={};return _xo.apply(this,arguments);};
  XMLHttpRequest.prototype.setRequestHeader=function(n,v){this._h[n]=v;return _xs.apply(this,arguments);};
  XMLHttpRequest.prototype.send=function(b){
    window.__api.push({url:this._u,method:this._m,headers:JSON.stringify(this._h),body:typeof b==='string'?b.substring(0,500):null,type:'xhr'});
    return _xsn.apply(this,arguments);};
  var _WS=window.WebSocket;
  window.WebSocket=function(u,p){window.__wsu.push(u);
    var ws=p?new _WS(u,p):new _WS(u);
    ws.addEventListener('message',function(e){if(typeof e.data==='string'&&window.__wsm.length<300)window.__wsm.push({d:'r',m:e.data.substring(0,1000)});});
    var _s=ws.send.bind(ws);ws.send=function(d){if(typeof d==='string'&&window.__wsm.length<300)window.__wsm.push({d:'s',m:d.substring(0,1000)});return _s(d);};
    return ws;};window.WebSocket.prototype=_WS.prototype;window.__p=true;}
""")

print("⏳ Waiting 15s for traffic (click around the Tradovate UI)...")
time.sleep(15)

api_calls = driver.execute_script("return window.__api||[];")
ws_msgs = driver.execute_script("return window.__wsm||[];")
ws_urls = driver.execute_script("return window.__wsu||[];")

print(f"\n── HTTP Calls ({len(api_calls)}) ──")
seen = set()
for c in api_calls:
    u = c.get('url','')
    if u not in seen:
        seen.add(u)
        print(f"  [{c.get('method','?')}] {u}")
        try:
            h = json.loads(c.get('headers','{}'))
            if 'Authorization' in h:
                av = h['Authorization']
                if not token:
                    token = av.replace('Bearer ',''); token_source = f"intercepted from {u}"
                print(f"       🔑 {av[:80]}...")
        except: pass
        if c.get('body'):
            print(f"       Body: {c['body'][:200]}")

print(f"\n── WebSocket URLs ({len(ws_urls)}) ──")
for u in ws_urls:
    print(f"  {u}")

if ws_msgs:
    print(f"\n── WebSocket Messages (first 50 of {len(ws_msgs)}) ──")
    for msg in ws_msgs[:50]:
        arrow = "→" if msg['d'] == 's' else "←"
        print(f"  {arrow} {msg['m'][:300]}")

# ── Probe REST API ────────────────────────────────────────────
if token:
    print(f"\n{'='*70}")
    print(f"🔬 PROBING TRADOVATE REST API")
    print(f"{'='*70}")
    import requests

    for base in ["https://demo.tradovateapi.com/v1", "https://live.tradovateapi.com/v1"]:
        hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        print(f"\n🌍 {base}")
        try:
            r = requests.get(f"{base}/me", headers=hdrs, timeout=5)
            if r.status_code == 401:
                print(f"   ❌ Auth failed"); continue
            print(f"   ✅ /me: {json.dumps(r.json(), indent=2)[:400]}")
        except Exception as e:
            print(f"   ❌ {e}"); continue

        endpoints = [
            "/account/list", "/cashBalance/list", "/fill/list", "/order/list",
            "/position/list", "/executionReport/list", "/tradingPermission/list",
            "/marginSnapshot/list", "/user/list", "/contract/list", "/product/list",
            "/exchange/list", "/userPlugin/list", "/userProperty/list",
            "/contactInfo/list", "/userSession/list", "/userAccountAutoLiq/list",
            "/userAccountRiskParameter/list", "/orderVersion/list", "/fillFee/list",
            "/command/list", "/commandReport/list",
        ]

        accounts = []
        for ep in endpoints:
            try:
                r = requests.get(f"{base}{ep}", headers=hdrs, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    n = len(data) if isinstance(data, list) else 1
                    print(f"   ✅ {ep} — {n} items")
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        print(f"      Keys: {list(data[0].keys())}")
                        for item in data[:3]:
                            print(f"      → {json.dumps(item)[:300]}")
                    elif isinstance(data, dict):
                        print(f"      → {json.dumps(data)[:300]}")
                    if ep == "/account/list":
                        accounts = data if isinstance(data, list) else []
                elif r.status_code != 404:
                    print(f"   ⚠️ {ep} — {r.status_code}")
            except: pass

        # Per-account deep dive
        for acc in accounts[:10]:
            aid = acc.get('id')
            aname = acc.get('name', '?')
            print(f"\n   📋 Account: {aname} (id={aid})")
            for sub in ['fill', 'order', 'position', 'cashBalance', 'cashBalanceLog',
                        'marginSnapshot', 'tradingPermission', 'executionReport', 'fillFee']:
                try:
                    r2 = requests.get(f"{base}/{sub}/ldeps?masterids={aid}", headers=hdrs, timeout=10)
                    if r2.status_code == 200:
                        items = r2.json()
                        if items:
                            print(f"      {sub}: {len(items)} items")
                            if isinstance(items[0], dict):
                                print(f"        Keys: {list(items[0].keys())}")
                                for it in items[:3]:
                                    print(f"        → {json.dumps(it)[:300]}")
                except: pass

            # Cash balance snapshot
            try:
                r3 = requests.post(f"{base}/cashBalance/getCashBalanceSnapshot",
                                   headers=hdrs, json={"accountId": aid}, timeout=8)
                if r3.status_code == 200:
                    print(f"      💰 Snapshot: {json.dumps(r3.json())[:300]}")
            except: pass

        print(f"\n{'='*70}")
        print("📝 SUMMARY")
        print(f"{'='*70}")
        print(f"Base: {base}")
        print(f"Token: {token_source}")
        print(f"Accounts: {len(accounts)}")
        for a in accounts:
            print(f"  - {a.get('name')} (id={a.get('id')}, active={a.get('active')})")
        break
else:
    print("\n❌ No auth token found.")

print("\n👉 Press ENTER to close browser...")
input()
driver.quit()
