"""
Explore FundedNext billing + accounts using the already-open Chrome.
Finds the Chrome debug port dynamically.
"""
import time
import json
import re
import subprocess
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Find the debug port by checking which ports 9500-9549 are listening
print("Scanning for Chrome debug ports...")
driver = None

for port in range(9500, 9550):
    try:
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        d = webdriver.Chrome(options=opts)
        url = d.current_url
        print(f"  Port {port}: Connected! URL={url}")
        if "fundednext" in url.lower():
            driver = d
            print(f"  >>> Using this one (FundedNext)")
            break
        else:
            driver = d  # keep as fallback
    except Exception:
        pass

if not driver:
    print("No Chrome debug port found in 9500-9549 range")
    exit(1)

print(f"\nConnected. Current URL: {driver.current_url}")

# ============================================================
# STEP 1: Accounts page - Futures tab
# ============================================================
print("\n" + "="*80)
print("STEP 1: Accounts page (click Futures, then scrape)")
print("="*80)

driver.get("https://app.fundednext.com/accounts")
time.sleep(4)

# Click Futures tab
try:
    # Look for tab-like buttons
    all_btns = driver.find_elements(By.CSS_SELECTOR, "button, div[role='tab'], span.ant-tag")
    for btn in all_btns:
        txt = btn.text.strip()
        if txt == "Futures":
            btn.click()
            print(f"Clicked '{txt}' tab")
            time.sleep(2)
            break
    else:
        # Try xpath
        futures = driver.find_elements(By.XPATH, "//*[text()='Futures']")
        for f in futures:
            try:
                f.click()
                print(f"Clicked Futures via xpath (tag={f.tag_name})")
                time.sleep(2)
                break
            except:
                pass
except Exception as e:
    print(f"Futures tab click error: {e}")

# Dump all text from the account cards
cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
print(f"\nFound {len(cards)} dashboard cards")

account_map = {}  # account_number -> card_info
for i, card in enumerate(cards):
    text = card.text.strip()
    print(f"\n--- Account Card {i+1} ---")
    for line in text.split('\n'):
        print(f"  {line.strip()}")
    
    # Extract FNFT account number
    fnft_match = re.search(r'FNFT\w+', text)
    if fnft_match:
        acct_num = fnft_match.group()
        account_map[acct_num] = text
        print(f"  >> Tradovate acct: {acct_num}")

    # Check for any numeric account IDs in the HTML
    html = card.get_attribute("innerHTML")
    numeric_ids = re.findall(r'\b\d{8,12}\b', html)
    if numeric_ids:
        print(f"  >> Numeric IDs in HTML: {numeric_ids}")

    # Check data attributes
    for attr in ['data-id', 'data-account-id', 'data-account', 'id']:
        val = card.get_attribute(attr)
        if val:
            print(f"  >> {attr}={val}")

# Also check parent wrappers for data attributes
wrappers = driver.find_elements(By.CSS_SELECTOR, ".account-wrapper__content .tw-w-full")
print(f"\nFound {len(wrappers)} account wrappers")
for i, w in enumerate(wrappers):
    html = w.get_attribute("outerHTML")[:800]
    print(f"\n--- Wrapper {i+1} HTML ---")
    print(html)

# ============================================================
# STEP 2: Try clicking Dashboard button on a card to see URL
# ============================================================
print("\n" + "="*80)
print("STEP 2: Check Dashboard button URLs")
print("="*80)

dash_buttons = driver.find_elements(By.XPATH, 
    "//button[contains(@class,'activeBusinessType')] | //button[contains(text(),'Dashboard')]")
print(f"Found {len(dash_buttons)} Dashboard buttons")
for i, btn in enumerate(dash_buttons):
    # Don't click, just check for data attributes or onclick
    onclick = btn.get_attribute("onclick") or ""
    data_attrs = {a: btn.get_attribute(a) for a in ['data-id', 'data-account', 'href'] if btn.get_attribute(a)}
    parent_html = btn.find_element(By.XPATH, "..").get_attribute("outerHTML")[:300]
    print(f"\n  Dashboard btn {i+1}: text='{btn.text}' onclick='{onclick}'")
    if data_attrs:
        print(f"  data attrs: {data_attrs}")
    # Check URL pattern if it's an anchor
    if btn.tag_name == "a":
        print(f"  href: {btn.get_attribute('href')}")

# ============================================================
# STEP 3: Billing page - check account_no column for FNFT reference
# ============================================================
print("\n" + "="*80)
print("STEP 3: Billing page deep inspection")
print("="*80)

driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(4)

# Check for type tabs on billing page
all_btns = driver.find_elements(By.CSS_SELECTOR, "button, div[role='tab']")
tab_texts = [(b.text.strip(), b.tag_name, b.get_attribute("class") or "") for b in all_btns if b.text.strip() in ("CFDs", "Futures", "All")]
print(f"Billing page tabs: {tab_texts}")

for btn in all_btns:
    if btn.text.strip() == "Futures":
        btn.click()
        print("Clicked Futures on billing page")
        time.sleep(2)
        break

# Get headers
try:
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".ant-table-wrapper table"))
    )
except:
    pass

headers = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table thead th")
header_texts = [h.text.strip() for h in headers]
print(f"Headers: {header_texts}")

rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table tbody tr.ant-table-row")
print(f"Rows: {len(rows)}")

for i, row in enumerate(rows):
    cells = row.find_elements(By.TAG_NAME, "td")
    print(f"\n--- Billing Row {i+1} ---")
    for j, cell in enumerate(cells):
        header = header_texts[j] if j < len(header_texts) else f"Col{j}"
        text = cell.text.strip()
        print(f"  {header}: {text}")
        # Check cell innerHTML for hidden data
        inner = cell.get_attribute("innerHTML")
        if "FNFT" in inner:
            print(f"    *** FNFT found in cell HTML! ***")
            print(f"    HTML: {inner[:200]}")
        # Check for links
        links = cell.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if href:
                print(f"    Link: {href}")

    # Full row HTML check
    row_html = row.get_attribute("innerHTML")
    numeric_ids = re.findall(r'\b\d{8,12}\b', row_html)
    fnft_refs = re.findall(r'FNFT\w+', row_html)
    if fnft_refs:
        print(f"  >> FNFT refs in row HTML: {fnft_refs}")

# ============================================================
# STEP 4: Check network/API calls by intercepting fetch
# ============================================================
print("\n" + "="*80)
print("STEP 4: Intercept API calls")
print("="*80)

# Inject a fetch interceptor to capture the next API calls
driver.execute_script("""
    window.__captured_responses = [];
    const origFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await origFetch.apply(this, args);
        const clone = response.clone();
        try {
            const body = await clone.text();
            window.__captured_responses.push({
                url: args[0],
                status: response.status,
                body: body.substring(0, 2000)
            });
        } catch(e) {}
        return response;
    };
""")

# Now reload billing page to capture the API call
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)

captured = driver.execute_script("return window.__captured_responses || [];")
print(f"Captured {len(captured)} API responses:")
for resp in captured:
    url = resp.get("url", "?")
    status = resp.get("status", "?")
    body = resp.get("body", "")[:500]
    print(f"\n  URL: {url}")
    print(f"  Status: {status}")
    if "account" in body.lower() or "fnft" in body.lower() or "billing" in body.lower():
        print(f"  Body: {body}")
    else:
        print(f"  Body (first 100): {body[:100]}")

# ============================================================
# STEP 5: Check the accounts API directly
# ============================================================
print("\n" + "="*80)
print("STEP 5: Check accounts page API responses")
print("="*80)

driver.execute_script("""
    window.__captured_responses = [];
""")

driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

captured = driver.execute_script("return window.__captured_responses || [];")
print(f"Captured {len(captured)} API responses:")
for resp in captured:
    url = resp.get("url", "?")
    body = resp.get("body", "")
    print(f"\n  URL: {url}")
    # Look for account mapping data
    if any(term in body for term in ["FNFT", "945576", "account_no", "tradovate"]):
        print(f"  MATCH! Body: {body[:1000]}")
    else:
        print(f"  Body (first 100): {body[:100]}")

print("\n" + "="*80)
print("DONE - Summary")
print("="*80)
print(f"Tradovate accounts found on cards: {list(account_map.keys())}")
