"""Explore FundedNext APIs by intercepting network calls via CDP."""
import time, json, re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Connected! URL: {driver.current_url}")

# Use Chrome DevTools Protocol to capture network requests
driver.execute_cdp_cmd("Network.enable", {})

# Navigate to accounts page
print("\n=== ACCOUNTS PAGE ===")
driver.get("https://app.fundednext.com/accounts")
time.sleep(6)

# Click Futures
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        print(f"Clicked Futures (tag={el.tag_name})")
        time.sleep(3)
        break
    except:
        pass

# Get the account card info
cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
print(f"\n{len(cards)} dashboard cards:")
for i, card in enumerate(cards):
    print(f"  Card {i+1}: {card.text.strip()}")

# Try to get network responses via performance log
# Alternative: use JavaScript to directly call the API
print("\n=== Trying direct API calls ===")

# Check cookies/auth tokens
cookies = driver.get_cookies()
auth_cookies = {c['name']: c['value'] for c in cookies if any(k in c['name'].lower() for k in ['token', 'auth', 'session', 'jwt'])}
print(f"Auth-related cookies: {list(auth_cookies.keys())}")

all_cookies = {c['name']: c['value'] for c in cookies}
print(f"All cookie names: {list(all_cookies.keys())}")

# Check localStorage for tokens
ls_keys = driver.execute_script("return Object.keys(localStorage);")
print(f"\nlocalStorage keys: {ls_keys}")

for key in ls_keys:
    val = driver.execute_script(f"return localStorage.getItem('{key}');")
    if any(t in key.lower() for t in ['token', 'auth', 'user', 'account']):
        print(f"  {key}: {str(val)[:200]}")

# Try to find API base URL from page source / scripts
print("\n=== Looking for API endpoints in page ===")

# Check if there's a __NEXT_DATA__ or similar
next_data = driver.execute_script("return document.getElementById('__NEXT_DATA__')?.textContent || '';")
if next_data:
    try:
        nd = json.loads(next_data)
        print(f"__NEXT_DATA__ keys: {list(nd.keys())}")
        if 'props' in nd:
            print(f"  props keys: {list(nd['props'].keys())}")
    except:
        print(f"__NEXT_DATA__: {next_data[:300]}")

# Check for React/Redux state
redux_state = driver.execute_script("""
    // Try common state storage patterns
    if (window.__REDUX_STATE__) return JSON.stringify(window.__REDUX_STATE__).substring(0, 3000);
    if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__).substring(0, 3000);
    if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__).substring(0, 3000);
    return null;
""")
if redux_state:
    print(f"Redux/State: {redux_state[:500]}")

# Try to use fetch directly within the browser context to call APIs
print("\n=== Direct API probing ===")

# Common FundedNext API patterns
api_tests = [
    "/api/accounts",
    "/api/billing",
    "/api/v1/accounts",
    "/api/v1/billing",
    "/api/user/accounts",
    "/api/dashboard/accounts",
]

for endpoint in api_tests:
    result = driver.execute_script(f"""
        try {{
            const resp = await fetch('{endpoint}');
            const text = await resp.text();
            return {{status: resp.status, body: text.substring(0, 1000)}};
        }} catch(e) {{
            return {{error: e.toString()}};
        }}
    """)
    if result and result.get('status') != 404:
        print(f"  {endpoint}: {result}")

# Now go to billing page
print("\n=== BILLING PAGE ===")
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)

# Check for Futures tab
for el in driver.find_elements(By.XPATH, "//*[text()='Futures']"):
    try:
        el.click()
        print(f"Clicked Futures on billing (tag={el.tag_name})")
        time.sleep(3)
        break
    except:
        pass

# Get table data
headers = [h.text.strip() for h in driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table thead th")]
rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table tbody tr.ant-table-row")
print(f"\nHeaders: {headers}")
print(f"Rows: {len(rows)}")

for i, row in enumerate(rows):
    cells = row.find_elements(By.TAG_NAME, "td")
    cell_data = {}
    for j, cell in enumerate(cells):
        h = headers[j] if j < len(headers) else f"col{j}"
        cell_data[h] = cell.text.strip()
        # Check for expandable/clickable elements
        clickables = cell.find_elements(By.CSS_SELECTOR, "a, button, [role='button'], .ant-btn")
        if clickables:
            cell_data[f"{h}_clickable"] = [c.text or c.get_attribute("class") for c in clickables]
    print(f"\n  Row {i+1}: {cell_data}")
    
    # Deep inspect: get ALL attributes of the row
    row_attrs = driver.execute_script("""
        const el = arguments[0];
        const attrs = {};
        for (const a of el.attributes) attrs[a.name] = a.value;
        // Also check data in React fiber
        const fiberKey = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (fiberKey) {
            const fiber = el[fiberKey];
            if (fiber && fiber.memoizedProps) {
                const record = fiber.memoizedProps.record || fiber.memoizedProps['data-row-key'] || fiber.memoizedProps;
                attrs['__react_record'] = JSON.stringify(record).substring(0, 1000);
            }
        }
        return attrs;
    """, row)
    
    if '__react_record' in row_attrs:
        print(f"  REACT DATA: {row_attrs['__react_record']}")
    if 'data-row-key' in row_attrs:
        print(f"  data-row-key: {row_attrs['data-row-key']}")

# Check the Ant Design table's internal data source
print("\n=== Ant Table data source ===")
table_data = driver.execute_script("""
    // Find the Ant Design table component via React fiber
    const table = document.querySelector('.ant-table-wrapper');
    if (!table) return null;
    const fiberKey = Object.keys(table).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    if (!fiberKey) return 'no fiber';
    
    // Walk up the fiber tree to find the Table component with dataSource
    let fiber = table[fiberKey];
    let depth = 0;
    while (fiber && depth < 30) {
        if (fiber.memoizedProps && fiber.memoizedProps.dataSource) {
            return JSON.stringify(fiber.memoizedProps.dataSource).substring(0, 5000);
        }
        if (fiber.memoizedProps && fiber.memoizedProps.data) {
            return JSON.stringify(fiber.memoizedProps.data).substring(0, 5000);
        }
        fiber = fiber.return;
        depth++;
    }
    return 'no dataSource found after ' + depth + ' levels';
""")

if table_data:
    print(f"Table dataSource: {table_data[:2000]}")
    try:
        parsed = json.loads(table_data)
        if isinstance(parsed, list) and parsed:
            print(f"\nFirst record keys: {list(parsed[0].keys())}")
            print(f"First record: {json.dumps(parsed[0], indent=2)}")
    except:
        pass

print("\nDONE")
