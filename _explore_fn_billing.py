"""Explore FundedNext Billing & Payouts page structure"""
import re, sys, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

sys.stdout.reconfigure(encoding='utf-8')

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"Current URL: {driver.current_url}")

# Step 1: Find the nav/sidebar links
print("\n=== NAVIGATION LINKS ===")
nav_links = driver.find_elements(By.CSS_SELECTOR, "a[href], nav a, [class*='sidebar'] a, [class*='menu'] a, [class*='nav'] a")
seen = set()
for link in nav_links:
    href = link.get_attribute("href") or ""
    text = link.text.strip()[:80]
    if href and text and href not in seen and "fundednext" in href:
        seen.add(href)
        print(f"  {text:40s} -> {href}")

# Step 2: Look specifically for billing/payout links
print("\n=== BILLING/PAYOUT LINKS ===")
keywords = ["billing", "payout", "payment", "invoice", "purchase", "fee", "transaction", "order", "subscription"]
for kw in keywords:
    els = driver.find_elements(By.XPATH, f"//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')]")
    for el in els:
        href = el.get_attribute("href") or ""
        text = el.text.strip()[:80]
        cls = (el.get_attribute("class") or "")[:100]
        print(f"  [{kw}] text='{text}' href='{href}' class='{cls}'")
    # Also check href containing keyword
    els2 = driver.find_elements(By.CSS_SELECTOR, f"a[href*='{kw}']")
    for el in els2:
        href = el.get_attribute("href") or ""
        text = el.text.strip()[:80]
        if href not in [e.get_attribute("href") for e in els]:
            print(f"  [{kw} href] text='{text}' href='{href}'")

# Step 3: Check sidebar/menu structure
print("\n=== SIDEBAR/MENU ELEMENTS ===")
for sel in ["[class*='sidebar']", "[class*='Sidebar']", "[class*='menu']", "[class*='Menu']", 
            "[class*='nav-']", "aside", "[class*='drawer']"]:
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in elems:
            text = el.text.strip()
            if text and len(text) > 5 and len(text) < 500:
                cls = (el.get_attribute("class") or "")[:100]
                print(f"  [{sel}] class='{cls}'")
                print(f"    Text: {text[:300]}")
    except:
        pass

# Step 4: Try navigating to billing page directly (common URLs)
billing_urls = [
    "https://app.fundednext.com/billing",
    "https://app.fundednext.com/billing-and-payouts",
    "https://app.fundednext.com/payouts",
    "https://app.fundednext.com/payments",
    "https://app.fundednext.com/transactions",
    "https://app.fundednext.com/orders",
]
print("\n=== TRYING BILLING URLs ===")
for url in billing_urls:
    driver.get(url)
    time.sleep(2)
    final_url = driver.current_url
    title = driver.title
    body_start = driver.find_element(By.TAG_NAME, "body").text[:200]
    redirected = " (REDIRECTED)" if final_url != url else ""
    print(f"\n  {url}")
    print(f"  -> {final_url}{redirected}")
    print(f"  Title: {title}")
    print(f"  Body: {body_start[:150]}")
    if "/accounts" not in final_url and final_url != url:
        # This might be the right page
        print(f"  *** INTERESTING - different redirect destination ***")

# Go back to accounts
driver.get("https://app.fundednext.com/accounts")
time.sleep(2)

print("\n=== ALL <a> HREFS ON PAGE ===")
all_links = driver.find_elements(By.TAG_NAME, "a")
unique_hrefs = set()
for a in all_links:
    href = a.get_attribute("href") or ""
    if href and "fundednext" in href and href not in unique_hrefs:
        unique_hrefs.add(href)
        text = a.text.strip()[:60]
        print(f"  {text:40s} -> {href}")

print("\nDone!")
