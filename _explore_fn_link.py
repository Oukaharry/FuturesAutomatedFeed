"""
Explore FundedNext to find the link between billing account_no and Tradovate account.

Plan:
1. Connect to existing FundedNext browser session
2. Go to accounts page → Futures → Active → scrape ALL text from each card
3. Go to billing page → scrape ALL columns including any hidden data
4. Look for overlapping identifiers
"""
import sys, time, json
sys.path.insert(0, r"C:\Users\harry\Music\MT5HedgingEngine")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Connect to existing Chrome debug session (if running), else launch fresh
opts = webdriver.ChromeOptions()
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
driver = webdriver.Chrome(options=opts)

print("=== Opening FundedNext ===")
driver.get("https://app.fundednext.com/accounts")
input(">>> Log in to FundedNext, then press Enter...")

# ── 1. ACCOUNTS PAGE ──
print("\n=== ACCOUNTS PAGE ===")
driver.get("https://app.fundednext.com/accounts")
time.sleep(3)

# Click Futures tab
tabs = driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab")
for tab in tabs:
    if "Futures" in tab.text:
        tab.click()
        time.sleep(2)
        print("Clicked Futures tab")
        break

# Click Active tab
buttons = driver.find_elements(By.CSS_SELECTOR, ".account-wrapper__create-account button")
for btn in buttons:
    if "Active" in btn.text:
        btn.click()
        time.sleep(2)
        print("Clicked Active tab")
        break

# Scrape all card data
cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
print(f"\nFound {len(cards)} account cards:")
account_cards = []
for i, card in enumerate(cards):
    text = card.text.strip()
    print(f"\n--- Card {i+1} ---")
    print(text)
    
    # Also get all <p> tags within the card
    p_tags = card.find_elements(By.TAG_NAME, "p")
    card_data = {"full_text": text, "p_tags": []}
    for p in p_tags:
        p_text = p.text.strip()
        if p_text:
            card_data["p_tags"].append(p_text)
    
    # Get h3 title
    h3s = card.find_elements(By.TAG_NAME, "h3")
    for h3 in h3s:
        card_data["h3"] = h3.text.strip()
    
    # Get ALL attributes and inner HTML
    card_data["innerHTML_preview"] = card.get_attribute("innerHTML")[:2000]
    account_cards.append(card_data)

# Also check if there's an Account ID visible anywhere
print("\n\n=== Looking for numeric account IDs on accounts page ===")
body_text = driver.find_element(By.TAG_NAME, "body").text
import re
numeric_ids = re.findall(r'\b\d{6,12}\b', body_text)
print(f"Numeric IDs found: {numeric_ids}")

# Check page source for hidden account IDs
page_source = driver.page_source
# Look for the billing account number in page source
print("\n=== Searching page source for '945576089' ===")
if "945576089" in page_source:
    idx = page_source.index("945576089")
    print(f"FOUND at position {idx}:")
    print(page_source[max(0,idx-200):idx+200])
else:
    print("Not found in accounts page source")

# ── 2. BILLING PAGE ──
print("\n\n=== BILLING PAGE ===")
driver.get("https://app.fundednext.com/billing/billing-history")
time.sleep(3)

# Check for Futures/CFDs tabs on billing page too
billing_tabs = driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab")
print(f"Billing page tabs: {[t.text.strip() for t in billing_tabs]}")
for tab in billing_tabs:
    if "Futures" in tab.text:
        tab.click()
        time.sleep(2)
        print("Clicked Futures tab on billing")
        break

# Wait for table
time.sleep(2)
table_rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table tbody tr.ant-table-row")
print(f"\nFound {len(table_rows)} billing rows:")

# Get headers first
headers = driver.find_elements(By.CSS_SELECTOR, ".ant-table-wrapper table thead th")
header_texts = [h.text.strip() for h in headers]
print(f"Headers: {header_texts}")

for i, row in enumerate(table_rows):
    cells = row.find_elements(By.TAG_NAME, "td")
    cell_texts = [c.text.strip() for c in cells]
    print(f"\nRow {i+1}: {cell_texts}")
    
    # Check for clickable elements or links in each cell
    for j, cell in enumerate(cells):
        links = cell.find_elements(By.TAG_NAME, "a")
        buttons = cell.find_elements(By.TAG_NAME, "button")
        if links:
            for link in links:
                print(f"  Cell {j} has link: href={link.get_attribute('href')}, text={link.text}")
        if buttons:
            for btn in buttons:
                print(f"  Cell {j} has button: text={btn.text}")
    
    # Check row attributes
    row_html = row.get_attribute("innerHTML")[:1000]
    # Look for FNFT in the row HTML
    if "FNFT" in row_html:
        print(f"  >>> FNFT found in row HTML!")
        fnft_idx = row_html.index("FNFT")
        print(f"  Context: ...{row_html[max(0,fnft_idx-100):fnft_idx+100]}...")

# ── 3. Check billing page source for FNFT ──
print("\n\n=== Searching billing page source for FNFT ===")
billing_source = driver.page_source
fnft_matches = [(m.start(), billing_source[max(0,m.start()-100):m.start()+100]) 
                for m in re.finditer(r'FNFT', billing_source)]
if fnft_matches:
    for pos, ctx in fnft_matches[:5]:
        print(f"FNFT at {pos}: ...{ctx}...")
else:
    print("FNFT not found in billing page source")

# ── 4. Check for expandable rows ──
print("\n\n=== Checking for expandable rows ===")
expand_btns = driver.find_elements(By.CSS_SELECTOR, ".ant-table-row-expand-icon, [class*='expand']")
print(f"Expand buttons: {len(expand_btns)}")
for btn in expand_btns[:3]:
    print(f"  Expand btn: class={btn.get_attribute('class')}, text={btn.text}")

# ── 5. Network/API exploration ──
print("\n\n=== Checking for billing API data in window.__NEXT_DATA__ or similar ===")
try:
    next_data = driver.execute_script("return window.__NEXT_DATA__")
    if next_data:
        print(f"__NEXT_DATA__ found: {json.dumps(next_data, indent=2)[:3000]}")
except Exception:
    print("No __NEXT_DATA__")

try:
    # Check for any React state or store
    data = driver.execute_script("""
        // Try to find billing data in React fiber
        var tables = document.querySelectorAll('.ant-table-wrapper');
        var results = [];
        tables.forEach(function(t) {
            var key = Object.keys(t).find(k => k.startsWith('__reactFiber'));
            if (key) {
                results.push('Found React fiber on table');
            }
        });
        return results;
    """)
    print(f"React check: {data}")
except Exception as e:
    print(f"React check failed: {e}")

print("\n\n=== Done! ===")
input("Press Enter to close browser...")
driver.quit()
