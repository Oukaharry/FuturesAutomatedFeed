"""Use CDP Fetch to intercept the Futures tab request."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)

# Navigate fresh
d.get("https://app.fundednext.com/accounts")
time.sleep(5)
print("Page loaded", flush=True)

# Enable Network + Log domains via CDP
d.execute_cdp_cmd("Network.enable", {})
d.execute_cdp_cmd("Log.enable", {})

# Get console errors
d.execute_script("""
    window._consoleErrors = [];
    var origError = console.error;
    console.error = function() {
        window._consoleErrors.push(Array.from(arguments).map(String).join(' ').substring(0, 500));
        origError.apply(console, arguments);
    };
    window._unhandledErrors = [];
    window.addEventListener('error', function(e) {
        window._unhandledErrors.push(e.message + ' at ' + e.filename + ':' + e.lineno);
    });
    window.addEventListener('unhandledrejection', function(e) {
        window._unhandledErrors.push('Promise: ' + String(e.reason).substring(0, 500));
    });
""")

# Now click Futures - use JavaScript click to avoid Selenium hang
d.execute_script("""
    var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
    for (var i = 0; i < tabs.length; i++) {
        if (tabs[i].textContent.trim() === 'Futures') {
            tabs[i].click();
            break;
        }
    }
""")
print("JS clicked Futures", flush=True)

# Wait a bit for any XHR to fire
time.sleep(3)

# Check console errors
errors = d.execute_script("return window._consoleErrors || []")
print(f"\nConsole errors: {len(errors)}", flush=True)
for e in errors[:10]:
    print(f"  {e[:300]}", flush=True)

unhandled = d.execute_script("return window._unhandledErrors || []")
print(f"\nUnhandled errors: {len(unhandled)}", flush=True)
for e in unhandled[:10]:
    print(f"  {e[:300]}", flush=True)

# Check body text
body = d.execute_script("return document.body.innerText.substring(0, 1000)")
print(f"\nBody text: {body[:500]}", flush=True)

# Check network logs via CDP
logs = d.get_log('browser')
print(f"\nBrowser logs: {len(logs)}", flush=True)
for log in logs[-20:]:
    print(f"  [{log.get('level')}] {log.get('message', '')[:300]}", flush=True)

d.execute_cdp_cmd("Network.disable", {})
d.execute_cdp_cmd("Log.disable", {})

# Now try a completely different approach: 
# Navigate to billing page and extract React fiber data with account info
print("\n\n=== BILLING PAGE FIBER DATA ===", flush=True)
d.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)

# Check if billing page has Futures tab too
body = d.execute_script("return document.body.innerText.substring(0, 1500)")
print(f"Billing page: {body[:800]}", flush=True)

# Look at the billing table rows' React fiber props for hidden data
fiber_data = d.execute_script("""
    function getReactFiber(el) {
        var keys = Object.keys(el);
        for (var i = 0; i < keys.length; i++) {
            if (keys[i].indexOf('__reactFiber') !== -1) {
                return el[keys[i]];
            }
        }
        return null;
    }
    
    function extractAccountData(fiber, depth) {
        if (!fiber || depth > 30) return null;
        var props = fiber.memoizedProps;
        if (props) {
            var str = '';
            try { str = JSON.stringify(props); } catch(e) { str = ''; }
            if (str.indexOf('945576089') !== -1 || str.indexOf('FNFT') !== -1 || str.indexOf('account_name') !== -1 || str.indexOf('trading_account') !== -1) {
                return str.substring(0, 5000);
            }
        }
        // Try child
        var result = extractAccountData(fiber.child, depth + 1);
        if (result) return result;
        // Try sibling
        result = extractAccountData(fiber.sibling, depth + 1);
        if (result) return result;
        // Try return/parent
        result = extractAccountData(fiber.return, depth + 1);
        if (result) return result;
        return null;
    }
    
    // Try on table rows
    var rows = document.querySelectorAll('tr.ant-table-row, .ant-table-row');
    var results = [];
    for (var i = 0; i < rows.length; i++) {
        var fiber = getReactFiber(rows[i]);
        if (fiber) {
            // Look at the record data in the fiber
            var node = fiber;
            for (var j = 0; j < 10 && node; j++) {
                var p = node.memoizedProps;
                if (p && p.record) {
                    results.push(JSON.stringify(p.record).substring(0, 3000));
                    break;
                }
                if (p && p.data) {
                    results.push(JSON.stringify(p.data).substring(0, 3000));
                    break;
                }
                if (p && p.dataSource) {
                    results.push(JSON.stringify(p.dataSource).substring(0, 5000));
                    break;
                }
                node = node.return;
            }
        }
    }
    return results;
""")
print(f"\nFiber data from billing rows: {len(fiber_data)}", flush=True)
for fd in fiber_data:
    print(f"  {fd[:2000]}", flush=True)

# Also try to get the Ant Table's dataSource directly
ds = d.execute_script("""
    function getReactFiber(el) {
        var keys = Object.keys(el);
        for (var i = 0; i < keys.length; i++) {
            if (keys[i].indexOf('__reactFiber') !== -1) {
                return el[keys[i]];
            }
        }
        return null;
    }
    
    var table = document.querySelector('.ant-table-wrapper, .ant-table');
    if (!table) return {error: 'no table found'};
    
    var fiber = getReactFiber(table);
    if (!fiber) return {error: 'no fiber on table'};
    
    var node = fiber;
    for (var i = 0; i < 30 && node; i++) {
        var props = node.memoizedProps;
        if (props) {
            if (props.dataSource) {
                return {found: 'dataSource', data: JSON.stringify(props.dataSource).substring(0, 10000)};
            }
            if (props.data && Array.isArray(props.data)) {
                return {found: 'data', data: JSON.stringify(props.data).substring(0, 10000)};
            }
        }
        node = node.return;
    }
    return {error: 'no dataSource found in fiber tree'};
""")
print(f"\nTable dataSource: {json.dumps(ds, indent=2)[:5000]}", flush=True)

print("\nDONE", flush=True)
