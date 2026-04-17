"""
Explore FundedNext billing + accounts pages using the already-open Chrome session.
Goal: Find if billing account_no (numeric) can be linked to Tradovate account (FNFT...).
Also: Always click the Futures tab first.
"""
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Connect to the already-open Chrome instance launched by the trader app
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9444")

try:
    driver = webdriver.Chrome(options=opts)
    print(f"Connected to Chrome. Current URL: {driver.current_url}")
except Exception as e:
    # Try without debug port - maybe it was launched differently
    print(f"Could not connect to debug port 9444: {e}")
    print("Trying to find Chrome via Selenium session...")
    exit(1)

# ============================================================
# STEP 1: Go to Accounts page, click Futures tab, get account info
# ============================================================
print("\n" + "="*80)
print("STEP 1: Scraping accounts page (Futures tab)")
print("="*80)

driver.get("https://app.fundednext.com/accounts")
time.sleep(3)

# Click Futures tab
try:
    futures_tabs = driver.find_elements(By.XPATH, 
        "//button[contains(text(),'Futures')] | //div[contains(text(),'Futures')]")
    for tab in futures_tabs:
        if tab.text.strip() == "Futures":
            tab.click()
            print(f"Clicked Futures tab: '{tab.text}'")
            time.sleep(2)
            break
    else:
        print(f"Futures tab not found among: {[t.text for t in futures_tabs]}")
except Exception as e:
    print(f"Error clicking Futures tab: {e}")

# Get all dashboard cards
cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
print(f"\nFound {len(cards)} dashboard cards")

accounts_info = []
for i, card in enumerate(cards):
    text = card.text.strip()
    print(f"\n--- Card {i+1} ---")
    print(text)
    # Also get any data attributes or IDs
    outer_html = card.get_attribute("outerHTML")[:500]
    print(f"HTML snippet: {outer_html}")
    accounts_info.append({"card_text": text, "html_snippet": outer_html})

# ============================================================
# STEP 2: Go to Billing page, scrape full table
# ============================================================
print("\n" + "="*80)
print("STEP 2: Scraping billing history page")
print("="*80)

driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(3)

# Check for Futures tab on billing page too
try:
    all_buttons = driver.find_elements(By.TAG_NAME, "button")
    tab_buttons = [b for b in all_buttons if b.text.strip() in ("CFDs", "Futures", "All")]
    print(f"Tab buttons found on billing page: {[b.text for b in tab_buttons]}")
    for btn in tab_buttons:
        if btn.text.strip() == "Futures":
            btn.click()
            print("Clicked Futures tab on billing page")
            time.sleep(2)
            break
except Exception as e:
    print(f"Tab check: {e}")

# Wait for table
try:
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".ant-table-wrapper table"))
    )
except:
    print("Table didn't load")

# Get column headers
headers = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table thead th")
header_texts = [h.text.strip() for h in headers]
print(f"\nBilling table headers: {header_texts}")

# Get all rows
rows = driver.find_elements(By.CSS_SELECTOR, 
    ".ant-table-wrapper table tbody tr.ant-table-row")
print(f"Found {len(rows)} billing rows")

for i, row in enumerate(rows):
    cells = row.find_elements(By.TAG_NAME, "td")
    cell_texts = [c.text.strip() for c in cells]
    print(f"\n--- Row {i+1} ({len(cells)} cells) ---")
    for j, (header, cell_text) in enumerate(zip(header_texts, cell_texts)):
        print(f"  {header}: {cell_text}")
    
    # Check if any cell contains links or clickable elements
    for j, cell in enumerate(cells):
        links = cell.find_elements(By.TAG_NAME, "a")
        buttons = cell.find_elements(By.TAG_NAME, "button")
        if links:
            print(f"  [LINK in col {j}]: {[l.get_attribute('href') for l in links]}")
        if buttons:
            print(f"  [BUTTON in col {j}]: {[b.text for b in buttons]}")
    
    # Get raw HTML of the row to find hidden data
    row_html = row.get_attribute("innerHTML")
    if "FNFT" in row_html:
        print(f"  *** FOUND FNFT reference in row HTML! ***")
        print(f"  HTML: {row_html[:500]}")

# ============================================================
# STEP 3: Check if there's an account details API or page
# ============================================================
print("\n" + "="*80)
print("STEP 3: Check for account detail pages / API calls")
print("="*80)

# Check network requests captured in performance log
# Also check localStorage/sessionStorage for account mappings
try:
    local_storage = driver.execute_script("return JSON.stringify(localStorage);")
    parsed = json.loads(local_storage)
    print(f"\nlocalStorage keys: {list(parsed.keys())}")
    
    # Look for anything with account info
    for key, value in parsed.items():
        if any(term in str(value).upper() for term in ["FNFT", "945576089", "ACCOUNT"]):
            print(f"  KEY: {key}")
            val_str = str(value)[:300]
            print(f"  VALUE: {val_str}")
except Exception as e:
    print(f"localStorage check: {e}")

try:
    session_storage = driver.execute_script("return JSON.stringify(sessionStorage);")
    parsed = json.loads(session_storage)
    print(f"\nsessionStorage keys: {list(parsed.keys())}")
    for key, value in parsed.items():
        if any(term in str(value).upper() for term in ["FNFT", "945576089", "ACCOUNT"]):
            print(f"  KEY: {key}")
            val_str = str(value)[:300]
            print(f"  VALUE: {val_str}")
except Exception as e:
    print(f"sessionStorage check: {e}")

# ============================================================
# STEP 4: Try account-specific URL patterns
# ============================================================
print("\n" + "="*80)
print("STEP 4: Check for API endpoints in page source")
print("="*80)

# Check all script tags for API endpoint patterns
scripts = driver.find_elements(By.TAG_NAME, "script")
for s in scripts:
    src = s.get_attribute("src") or ""
    if "chunk" in src or "app" in src or "main" in src:
        print(f"Script: {src}")

# Try to intercept XHR by checking performance entries
try:
    perf_entries = driver.execute_script("""
        return performance.getEntriesByType('resource')
            .filter(e => e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch')
            .map(e => e.name);
    """)
    api_calls = [e for e in perf_entries if 'api' in e.lower() or 'account' in e.lower() or 'billing' in e.lower()]
    print(f"\nAPI/fetch calls captured ({len(api_calls)} relevant):")
    for call in api_calls[:20]:
        print(f"  {call}")
except Exception as e:
    print(f"Performance entries: {e}")

print("\n" + "="*80)
print("DONE")
print("="*80)
