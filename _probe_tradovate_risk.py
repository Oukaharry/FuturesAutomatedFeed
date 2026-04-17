"""
Comprehensive Tradovate Risk/Drawdown API probe.
Connects to ALL running Tradovate Selenium instances via their open Chrome debug ports
and probes every risk-related endpoint to find min equity / drawdown data.

Usage: Run this while the TradeOpsAI app is running with Tradovate connections active.
It will connect to each Selenium-managed Chrome instance and dump all risk data.
"""
import json, sys, os, subprocess, re

# Find Chrome debug ports from running Selenium instances
def find_chrome_debug_ports():
    """Find all Chrome instances with debug ports open."""
    ports = []
    try:
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=10
        )
        # Find listening ports from chrome.exe processes
        # First get all chrome.exe PIDs
        tasklist = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq chrome.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=10
        )
        chrome_pids = set()
        for line in tasklist.stdout.strip().split('\n')[1:]:
            parts = line.strip('"').split('","')
            if len(parts) >= 2:
                try:
                    chrome_pids.add(parts[1])
                except:
                    pass

        for line in result.stdout.split('\n'):
            if 'LISTENING' in line and '127.0.0.1' in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[4]
                    if pid in chrome_pids:
                        addr = parts[1]
                        port = int(addr.split(':')[-1])
                        if port > 1024:
                            ports.append((port, pid))
    except Exception as e:
        print(f"Error finding ports: {e}")
    return ports


def try_cdp_port(port):
    """Try to connect to a Chrome DevTools Protocol port and get tabs."""
    import urllib.request
    try:
        data = urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=3).read()
        tabs = json.loads(data)
        tradovate_tabs = [t for t in tabs if 'tradovate' in t.get('url', '').lower()
                          and t.get('webSocketDebuggerUrl')]
        return tradovate_tabs
    except:
        return []


def api_fetch_via_selenium(driver, endpoint, method="GET", body=None):
    """Execute a Tradovate API call via the browser's session."""
    body_js = f"opts.body = JSON.stringify({json.dumps(body)});" if body else ""
    js = f"""
    var cb = arguments[arguments.length - 1];
    (async function() {{
        try {{
            var auth = JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{{}}'  );
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
    try:
        return driver.execute_async_script(js)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def probe_account(driver, acc_id, acc_name):
    """Probe ALL risk/equity/drawdown endpoints for a single account."""
    print(f"\n{'='*80}")
    print(f"  ACCOUNT: {acc_name} (ID={acc_id})")
    print(f"{'='*80}")

    # ── 1. Cash Balance Snapshot ──
    print(f"\n  ── /cashBalance/getCashBalanceSnapshot (POST accountId={acc_id}) ──")
    r = api_fetch_via_selenium(driver, "/cashBalance/getCashBalanceSnapshot", "POST", {"accountId": acc_id})
    if r.get('ok') and r.get('data'):
        d = r['data']
        for k in sorted(d.keys()):
            print(f"    {k}: {d[k]}")
    else:
        print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 2. userAccountAutoLiq — ALL variations ──
    for ep_name, ep in [
        ("deps",   f"/userAccountAutoLiq/deps?masterid={acc_id}"),
        ("ldeps",  f"/userAccountAutoLiq/ldeps?masterids={acc_id}"),
        ("list",   "/userAccountAutoLiq/list"),
        ("find",   f"/userAccountAutoLiq/find?name={acc_id}"),
        ("item",   f"/userAccountAutoLiq/item?id={acc_id}"),
    ]:
        print(f"\n  ── /userAccountAutoLiq/{ep_name} ──")
        r = api_fetch_via_selenium(driver, ep)
        if r.get('ok') and r.get('data') is not None:
            data = r['data']
            if isinstance(data, list):
                print(f"    → {len(data)} entries")
                for entry in data:
                    for k in sorted(entry.keys()):
                        print(f"      {k}: {entry[k]}")
                    print()
            elif isinstance(data, dict):
                for k in sorted(data.keys()):
                    print(f"    {k}: {data[k]}")
            else:
                print(f"    → {data}")
        else:
            print(f"    FAILED: status={r.get('status')} error={r.get('error','')} raw={r.get('raw','')[:200]}")

    # ── 3. accountRiskStatus — ALL variations ──
    for ep_name, ep in [
        ("deps",   f"/accountRiskStatus/deps?masterid={acc_id}"),
        ("ldeps",  f"/accountRiskStatus/ldeps?masterids={acc_id}"),
        ("list",   "/accountRiskStatus/list"),
        ("item",   f"/accountRiskStatus/item?id={acc_id}"),
    ]:
        print(f"\n  ── /accountRiskStatus/{ep_name} ──")
        r = api_fetch_via_selenium(driver, ep)
        if r.get('ok') and r.get('data') is not None:
            data = r['data']
            if isinstance(data, list):
                print(f"    → {len(data)} entries")
                for entry in data:
                    for k in sorted(entry.keys()):
                        print(f"      {k}: {entry[k]}")
                    print()
            elif isinstance(data, dict):
                for k in sorted(data.keys()):
                    print(f"    {k}: {data[k]}")
        else:
            print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 4. userAccountRiskParameter ──
    for ep_name, ep in [
        ("deps",  f"/userAccountRiskParameter/deps?masterid={acc_id}"),
        ("list",  "/userAccountRiskParameter/list"),
    ]:
        print(f"\n  ── /userAccountRiskParameter/{ep_name} ──")
        r = api_fetch_via_selenium(driver, ep)
        if r.get('ok') and r.get('data') is not None:
            data = r['data']
            if isinstance(data, list):
                print(f"    → {len(data)} entries")
                for entry in data:
                    for k in sorted(entry.keys()):
                        print(f"      {k}: {entry[k]}")
                    print()
            elif isinstance(data, dict):
                for k in sorted(data.keys()):
                    print(f"    {k}: {data[k]}")
        else:
            print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 5. marginSnapshot ──
    for ep_name, ep in [
        ("deps",  f"/marginSnapshot/deps?masterid={acc_id}"),
        ("list",  "/marginSnapshot/list"),
    ]:
        print(f"\n  ── /marginSnapshot/{ep_name} ──")
        r = api_fetch_via_selenium(driver, ep)
        if r.get('ok') and r.get('data') is not None:
            data = r['data']
            if isinstance(data, list):
                print(f"    → {len(data)} entries")
                for entry in data[:3]:  # limit to 3
                    for k in sorted(entry.keys()):
                        print(f"      {k}: {entry[k]}")
                    print()
            elif isinstance(data, dict):
                for k in sorted(data.keys()):
                    print(f"    {k}: {data[k]}")
        else:
            print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 6. userAccountPositionLimit ──
    for ep_name, ep in [
        ("deps",  f"/userAccountPositionLimit/deps?masterid={acc_id}"),
        ("list",  "/userAccountPositionLimit/list"),
    ]:
        print(f"\n  ── /userAccountPositionLimit/{ep_name} ──")
        r = api_fetch_via_selenium(driver, ep)
        if r.get('ok') and r.get('data') is not None:
            data = r['data']
            if isinstance(data, list):
                print(f"    → {len(data)} entries")
                for entry in data[:3]:
                    for k in sorted(entry.keys()):
                        print(f"      {k}: {entry[k]}")
                    print()
            elif isinstance(data, dict):
                for k in sorted(data.keys()):
                    print(f"    {k}: {data[k]}")
        else:
            print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 7. tradingPermission ──
    print(f"\n  ── /tradingPermission/list ──")
    r = api_fetch_via_selenium(driver, "/tradingPermission/list")
    if r.get('ok') and r.get('data') is not None:
        data = r['data']
        if isinstance(data, list):
            print(f"    → {len(data)} entries")
            for entry in data[:5]:
                for k in sorted(entry.keys()):
                    print(f"      {k}: {entry[k]}")
                print()
    else:
        print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 8. Account item (full account details) ──
    print(f"\n  ── /account/item?id={acc_id} ──")
    r = api_fetch_via_selenium(driver, f"/account/item?id={acc_id}")
    if r.get('ok') and r.get('data'):
        d = r['data']
        for k in sorted(d.keys()):
            print(f"    {k}: {d[k]}")
    else:
        print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 9. Cash balance log (recent entries) ──
    print(f"\n  ── /cashBalanceLog/deps?masterid={acc_id} (last 5 entries) ──")
    r = api_fetch_via_selenium(driver, f"/cashBalanceLog/deps?masterid={acc_id}")
    if r.get('ok') and r.get('data'):
        data = r['data']
        if isinstance(data, list):
            print(f"    → {len(data)} total entries (showing last 5)")
            for entry in data[-5:]:
                ts = entry.get('timestamp', '')
                delta = entry.get('delta', '')
                remark = entry.get('currencyId', '')
                print(f"      {ts} | delta={delta} | keys={list(entry.keys())}")
    else:
        print(f"    FAILED: status={r.get('status')} raw={r.get('raw','')[:200]}")

    # ── 10. Check for WebSocket-delivered risk data in browser memory ──
    print(f"\n  ── Browser sessionStorage/localStorage risk keys ──")
    js = """
    var cb = arguments[arguments.length - 1];
    var result = {};
    ['sessionStorage', 'localStorage'].forEach(function(storeName) {
        var store = window[storeName];
        for (var i = 0; i < store.length; i++) {
            var key = store.key(i);
            var lk = key.toLowerCase();
            if (lk.indexOf('risk') >= 0 || lk.indexOf('liq') >= 0 || lk.indexOf('drawdown') >= 0 || 
                lk.indexOf('equity') >= 0 || lk.indexOf('margin') >= 0 || lk.indexOf('autoLiq') >= 0 ||
                lk.indexOf('balance') >= 0) {
                result[storeName + '/' + key] = store.getItem(key).substring(0, 500);
            }
        }
    });
    cb(result);
    """
    try:
        r = driver.execute_async_script(js)
        if r:
            for k in sorted(r.keys()):
                print(f"    {k}: {r[k]}")
        else:
            print(f"    (no risk-related keys found)")
    except Exception as e:
        print(f"    Error: {e}")

    # ── 11. Check the WebSocket sync state (Tradovate caches entity state) ──
    print(f"\n  ── Browser: Tradovate internal entity state (window.__tv_*) ──")
    js = """
    var cb = arguments[arguments.length - 1];
    var result = {};
    // Tradovate stores entity state in various places
    // Check for common patterns in the React/Redux store
    
    // Try to find risk-related data in the app's state
    var keys = Object.keys(window).filter(function(k) {
        return k.indexOf('__') >= 0 || k.indexOf('store') >= 0 || k.indexOf('State') >= 0;
    });
    result['_windowKeys'] = keys.join(', ');
    
    // Check if there's a Redux/MobX store accessible
    if (window.__REDUX_DEVTOOLS_EXTENSION__) {
        result['_redux'] = 'Redux DevTools detected';
    }
    
    cb(result);
    """
    try:
        r = driver.execute_async_script(js)
        if r:
            for k in sorted(r.keys()):
                val = str(r[k])[:200]
                print(f"    {k}: {val}")
    except Exception as e:
        print(f"    Error: {e}")

    # ── 12. Try to intercept WebSocket entity cache ──
    print(f"\n  ── Browser: Try to read Tradovate entity cache via sessionStorage ──")
    js = """
    var cb = arguments[arguments.length - 1];
    var result = {};
    // Tradovate stores full entity state under key 'tradovate_entity_state' or similar
    for (var i = 0; i < sessionStorage.length; i++) {
        var key = sessionStorage.key(i);
        var val = sessionStorage.getItem(key);
        // Show all keys and sizes
        result[key] = val.length + ' chars';
    }
    cb(result);
    """
    try:
        r = driver.execute_async_script(js)
        if r:
            print(f"    SessionStorage keys ({len(r)} total):")
            for k in sorted(r.keys()):
                print(f"      {k}: {r[k]}")
    except Exception as e:
        print(f"    Error: {e}")


def main():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    print("=" * 80)
    print("  TRADOVATE RISK/DRAWDOWN API COMPREHENSIVE PROBE")
    print("=" * 80)

    # Find all Chrome debug ports
    ports_pids = find_chrome_debug_ports()
    print(f"\nFound {len(ports_pids)} Chrome debug port candidates")

    tradovate_drivers = []

    for port, pid in ports_pids:
        tabs = try_cdp_port(port)
        if tabs:
            print(f"  Port {port} (PID {pid}): {len(tabs)} Tradovate tab(s)")
            try:
                opts = Options()
                opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
                driver = webdriver.Chrome(options=opts)

                # Get auth info
                auth_js = "return JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{}')"
                auth = driver.execute_script(auth_js)
                username = auth.get('username', '?')
                env = auth.get('environment', '?')
                print(f"    Connected: user={username} env={env}")

                tradovate_drivers.append((driver, username, env, port))
            except Exception as e:
                print(f"    Failed to connect: {e}")

    if not tradovate_drivers:
        print("\nNo Tradovate browser sessions found!")
        print("Make sure TradeOpsAI is running with Tradovate connections active.")
        sys.exit(1)

    for driver, username, env, port in tradovate_drivers:
        print(f"\n{'#'*80}")
        print(f"  SESSION: {username} ({env}) on port {port}")
        print(f"{'#'*80}")

        # Get accounts
        r = api_fetch_via_selenium(driver, "/account/list")
        if not r.get('ok') or not r.get('data'):
            print(f"  Failed to get accounts: {r}")
            continue

        accounts = r['data']
        print(f"\n  {len(accounts)} accounts found:")
        for a in accounts:
            print(f"    ID={a['id']}  Name={a.get('name','?')}  Active={a.get('active')}")

        # Probe each account
        for acc in accounts:
            probe_account(driver, acc['id'], acc.get('name', '?'))

    print(f"\n{'='*80}")
    print("  PROBE COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
