"""Scrape FundedNext Billing History and Payout History pages"""
import re, sys, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

sys.stdout.reconfigure(encoding='utf-8')

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)

for page_name, url in [("BILLING HISTORY", "https://app.fundednext.com/billing/billing-history"),
                        ("PAYOUT HISTORY", "https://app.fundednext.com/billing/payout-history")]:
    print(f"\n{'='*70}")
    print(f"  {page_name}: {url}")
    print(f"{'='*70}")
    
    driver.get(url)
    time.sleep(4)
    
    print(f"Final URL: {driver.current_url}")
    print(f"Title: {driver.title}")
    
    body = driver.find_element(By.TAG_NAME, "body")
    body_text = body.text
    
    # Dollar values
    dollars = re.findall(r'-?\$[\d,]+\.?\d*', body_text)
    print(f"\nDollar values: {dollars[:20]}")
    
    # Tables
    tables = driver.find_elements(By.TAG_NAME, "table")
    print(f"\nTables found: {len(tables)}")
    for ti, table in enumerate(tables[:5]):
        rows = table.find_elements(By.TAG_NAME, "tr")
        print(f"\n--- Table {ti} ({len(rows)} rows) ---")
        # Headers
        headers = table.find_elements(By.TAG_NAME, "th")
        if headers:
            print(f"  Headers: {' | '.join([h.text.strip()[:40] for h in headers])}")
        # Data rows
        for ri, row in enumerate(rows[:15]):
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            if cells:
                print(f"  Row {ri}: {' | '.join([c.text.strip()[:40] for c in cells])}")
    
    # Ant Design tables (common in this app)
    ant_tables = driver.find_elements(By.CSS_SELECTOR, ".ant-table, [class*='ant-table']")
    print(f"\nAnt Design tables: {len(ant_tables)}")
    
    # Card/list elements
    for sel in [".dashboard-card", "[class*='billing']", "[class*='Billing']", 
                "[class*='payout']", "[class*='Payout']", "[class*='history']",
                "[class*='History']", "[class*='transaction']", "[class*='invoice']",
                "[class*='order']", "[class*='payment']"]:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            meaningful = [e for e in elems if e.text.strip() and len(e.text.strip()) > 10]
            if meaningful:
                print(f"\n{sel}: {len(meaningful)} elements")
                for e in meaningful[:3]:
                    cls = (e.get_attribute("class") or "")[:100]
                    print(f"  class='{cls}'")
                    print(f"  text: {e.text.strip()[:300]}")
        except:
            pass
    
    # Tab/nav within billing
    print(f"\n--- Sub-navigation ---")
    for sel in [".ant-tabs-tab", "[class*='tab']", "a[href*='billing']", "a[href*='payout']"]:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in elems[:10]:
                text = e.text.strip()[:60]
                href = (e.get_attribute("href") or "")[:100]
                if text:
                    print(f"  [{sel}] text='{text}' href='{href}'")
        except:
            pass
    
    # Get wrapper/content area innerHTML
    print(f"\n--- Content area HTML ---")
    for sel in ["main", "[class*='content']", "[class*='wrapper']", ".ant-table-wrapper"]:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in elems[:2]:
                html = e.get_attribute("innerHTML")
                if html and len(html) > 100 and ("table" in html.lower() or "$" in html or "billing" in html.lower()):
                    cls = (e.get_attribute("class") or "")[:80]
                    print(f"\n  [{sel}] class='{cls}' innerHTML ({len(html)} chars):")
                    print(f"  {html[:2000]}")
                    break
        except:
            pass
    
    # Full body text
    print(f"\n--- Body text (first 3000 chars) ---")
    print(body_text[:3000])

print("\nDone!")
