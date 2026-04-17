"""Quick explore using port 9549."""
import time, json, re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# ---- Inject fetch interceptor BEFORE navigating ----
driver.execute_script("""
    window.__api_log = [];
    const _fetch = window.fetch;
    window.fetch = async function(...args) {
        const resp = await _fetch.apply(this, args);
        const clone = resp.clone();
        try {
            const txt = await clone.text();
            window.__api_log.push({url: typeof args[0]==='string'?args[0]:args[0].url, body: txt.substring(0,5000)});
        } catch(e){}
        return resp;
    };
    // Also intercept XMLHttpRequest
    const _open = XMLHttpRequest.prototype.open;
    const _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u) {
        this.__url = u;
        return _open.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        this.addEventListener('load', function() {
            try {
                window.__api_log.push({url: this.__url, body: this.responseText.substring(0, 5000)});
            } catch(e){}
        });
        return _send.apply(this, arguments);
    };
    console.log('Fetch/XHR interceptor installed');
""")
print("Interceptor installed")

# ---- STEP 1: Go to accounts page, click Futures ----
print("\n=== ACCOUNTS PAGE ===")
driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

# Click Futures
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        print(f"Clicked Futures (tag={el.tag_name})")
        time.sleep(3)
        break
    except:
        pass

# Grab API responses from accounts page
api_log = driver.execute_script("return window.__api_log || [];")
print(f"\nCaptured {len(api_log)} API calls on accounts page:")
for entry in api_log:
    url = entry.get("url", "?")
    body = entry.get("body", "")
    print(f"\n  URL: {url}")
    # Parse JSON body if possible
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            print(f"  Keys: {list(data.keys())}")
            # Look for account info
            for key in ['data', 'accounts', 'result', 'results']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list) and len(val) > 0:
                        print(f"  {key}[0] sample: {json.dumps(val[0], indent=2)[:800]}")
                    elif isinstance(val, dict):
                        print(f"  {key}: {json.dumps(val, indent=2)[:800]}")
        elif isinstance(data, list) and len(data) > 0:
            print(f"  Array[0]: {json.dumps(data[0], indent=2)[:800]}")
    except:
        if len(body) < 300:
            print(f"  Body: {body}")
        else:
            print(f"  Body[0:200]: {body[:200]}")

# Dump card info
cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
print(f"\n{len(cards)} dashboard cards:")
for i, card in enumerate(cards):
    print(f"\n  Card {i+1}: {card.text.strip()[:200]}")

# ---- STEP 2: Reset interceptor, go to billing ----
print("\n\n=== BILLING PAGE ===")
driver.execute_script("window.__api_log = [];")
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)

# Click Futures on billing page if available
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        print(f"Clicked Futures on billing (tag={el.tag_name})")
        time.sleep(3)
        break
    except:
        pass

# Grab API responses
api_log = driver.execute_script("return window.__api_log || [];")
print(f"\nCaptured {len(api_log)} API calls on billing page:")
for entry in api_log:
    url = entry.get("url", "?")
    body = entry.get("body", "")
    print(f"\n  URL: {url}")
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            print(f"  Keys: {list(data.keys())}")
            for key in ['data', 'billing', 'results', 'result', 'records']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list) and len(val) > 0:
                        print(f"  {key}[0]: {json.dumps(val[0], indent=2)[:1000]}")
                    elif isinstance(val, dict):
                        print(f"  {key}: {json.dumps(val, indent=2)[:1000]}")
        elif isinstance(data, list) and len(data) > 0:
            print(f"  Array[0]: {json.dumps(data[0], indent=2)[:1000]}")
    except:
        if len(body) < 300:
            print(f"  Body: {body}")
        else:
            print(f"  Body[0:200]: {body[:200]}")

# Also dump table data
headers = [h.text.strip() for h in driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table thead th")]
rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table tbody tr.ant-table-row")
print(f"\nTable headers: {headers}")
print(f"Table rows: {len(rows)}")
for i, row in enumerate(rows):
    cells = [c.text.strip() for c in row.find_elements(By.TAG_NAME, "td")]
    print(f"  Row {i+1}: {dict(zip(headers, cells))}")

print("\nDONE")
