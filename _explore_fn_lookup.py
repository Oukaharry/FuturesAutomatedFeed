"""Try account lookup by login ID and other approaches."""
import time, json, traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

out = []
def p(s):
    print(s, flush=True)
    out.append(str(s))

try:
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
    driver = webdriver.Chrome(options=opts)

    token = driver.execute_script("""
        var c = document.cookie.split(';').find(function(c) { return c.trim().indexOf('tokenV1=') === 0; });
        return c ? decodeURIComponent(c.split('=')[1]) : null;
    """)
    base = "https://api.fundednext.com/api/v1"

    # Try account detail/lookup endpoints
    endpoints = [
        "/get-account/945576089",
        "/account/945576089",
        "/account/detail/945576089",
        "/account/info/945576089",
        "/customer/account/945576089",
        "/account?login=945576089",
        "/get-accounts?login=945576089",
        "/get-accounts?type=active&page=1&limit=6&login=945576089",
        # Try Futures-specific endpoints 
        "/get-accounts?type=active&page=1&limit=6&is_futures=1",
        "/get-accounts?type=active&page=1&limit=6&is_futures=true",
        "/get-accounts?type=active&page=1&limit=6&account_type=futures",
        "/get-accounts?type=active&page=1&limit=20&plan_category=futures",
        "/get-accounts?type=active&page=1&limit=20&plan_type=futures_legacy",
        # Try plan IDs from the plan-wise-ids response
        # "stellar_1step" had plan IDs, "evaluation" had plan IDs
        # The user has "Futures Legacy Challenge" which is probably futures-specific
        "/futures/accounts?type=active&page=1&limit=6",
        "/get-futures-account?type=active&page=1&limit=6",
        "/account/get-details?login=945576089",
        "/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=945576089&page=1&limit=20",
    ]

    for ep in endpoints:
        url = f"{base}{ep}"
        result = driver.execute_script("""
            var url = arguments[0];
            var token = arguments[1];
            try {
                var resp = await fetch(url, {
                    headers: {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
                });
                var text = await resp.text();
                return {status: resp.status, body: text.substring(0, 5000)};
            } catch(e) {
                return {error: e.toString()};
            }
        """, url, token)
        if not result:
            continue
        if result.get('error'):
            continue
        status = result.get('status', 0)
        if status in (404, 405, 500):
            continue
        body = result.get('body', '')
        
        try:
            data = json.loads(body)
            # Check if there's account data
            data_str = json.dumps(data, default=str).lower()
            interesting = any(x in data_str for x in ['fnft', 'tradovate', 'account_name', 'server_name', 'futures_legacy'])
            has_data = False
            if isinstance(data.get('data'), dict):
                inner = data['data'].get('data', [])
                if isinstance(inner, list) and len(inner) > 0:
                    has_data = True
                elif not isinstance(inner, list) and data['data']:
                    has_data = True
            elif isinstance(data.get('data'), list) and len(data['data']) > 0:
                has_data = True
                
            if interesting or has_data or status == 200:
                p(f"\n{'='*50}")
                p(f"{ep} -> HTTP {status}")
                p(json.dumps(data, indent=2, default=str)[:3000])
        except:
            if status == 200:
                p(f"\n{ep} -> HTTP {status}: {body[:500]}")

    # Also: Try to navigate to the futures accounts page using RSC 
    p("\n\n=== TRYING RSC NAVIGATION ===")
    # The site uses React Server Components
    # When clicking tabs, it may use client-side transition
    # Let's navigate directly to a potential futures URL
    for url_try in [
        "https://app.fundednext.com/accounts?type=futures",
        "https://app.fundednext.com/accounts?tab=futures", 
        "https://app.fundednext.com/accounts?platform=futures",
        "https://app.fundednext.com/futures/accounts",
    ]:
        driver.get(url_try)
        time.sleep(3)
        text = driver.execute_script("return document.body.innerText.substring(0, 500);")
        has_fnft = 'FNFT' in text
        has_error = 'Something Went Wrong' in text or '404' in text
        p(f"\n  {url_try}")
        p(f"    FNFT present: {has_fnft}, Error: {has_error}")
        if has_fnft:
            p(f"    Text: {text[:500]}")

    # Final: go back to accounts and try clicking Futures after a fresh load
    p("\n\n=== FRESH LOAD + FUTURES TAB ===")
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(5)
    
    # Check if CFDs tab shows "active" and the page works
    text = driver.execute_script("return document.body.innerText.substring(0, 1000);")
    p(f"After fresh load: {'Something Went Wrong' not in text}")
    
    if 'Something Went Wrong' not in text:
        # Try clicking Futures tab via the parent div with role
        result = driver.execute_script("""
            // Find the Futures tab and click it properly
            var tabList = document.querySelector('[role="tablist"]');
            if (!tabList) return {error: 'No tablist found'};
            
            var tabs = tabList.querySelectorAll('[role="tab"]');
            for (var i = 0; i < tabs.length; i++) {
                if (tabs[i].textContent.trim() === 'Futures') {
                    tabs[i].click();
                    return {clicked: true, tabId: tabs[i].id, ariaControls: tabs[i].getAttribute('aria-controls')};
                }
            }
            
            // Try ant-tabs-tab-btn
            var btns = document.querySelectorAll('.ant-tabs-tab-btn');
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].textContent.trim() === 'Futures') {
                    btns[i].click();
                    return {clicked: true, via: 'ant-tabs-tab-btn'};
                }
            }
            return {error: 'Futures tab not found'};
        """)
        p(f"Click result: {result}")
        time.sleep(5)
        
        text2 = driver.execute_script("return document.body.innerText.substring(0, 2000);")
        has_error = 'Something Went Wrong' in text2
        has_fnft = 'FNFT' in text2
        p(f"After Futures click: error={has_error}, FNFT={has_fnft}")
        if has_fnft and not has_error:
            p(f"Text: {text2[:2000]}")

except Exception as e:
    traceback.print_exc()
    p(f"ERROR: {e}")

with open("_fn_lookup_output.txt", "w") as f:
    f.write("\n".join(out))
p(f"\nWritten to _fn_lookup_output.txt")
p("DONE")
