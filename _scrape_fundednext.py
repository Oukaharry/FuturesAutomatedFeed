"""Scrape the already-open FundedNext Selenium Chrome session"""
import re
import os
import sys
import time
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# The Selenium Chrome debug port (found via netstat)
debug_port = 9549
print(f"Connecting to Selenium Chrome on port {debug_port}...")

opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

driver = webdriver.Chrome(options=opts)

print(f"Connected! URL: {driver.current_url}")
print(f"Title: {driver.title}")

# Navigate to accounts page if not there
if "/accounts" not in driver.current_url:
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(3)

# Click the "Active" tab 
print("\n--- Clicking 'Active' tab ---")
try:
    active_btns = driver.find_elements(By.XPATH, "//*[contains(text(),'Active')]")
    for btn in active_btns:
        if btn.text.strip() == "Active":
            btn.click()
            print("Clicked 'Active' tab!")
            time.sleep(3)
            break
except Exception as e:
    print(f"Could not click Active tab: {e}")

# Get full page source for analysis
page_source = driver.page_source
print(f"\nPage source length: {len(page_source)}")

# Get body text
body = driver.find_element(By.TAG_NAME, "body")
body_text = body.text

# Dollar values
dollars = re.findall(r'-?\$[\d,]+\.?\d*', body_text)
print(f"\nDollar values found: {dollars[:30]}")

# Percentage values
percents = re.findall(r'-?\d+\.?\d*\s*%', body_text)
print(f"Percentage values: {percents[:20]}")

# Account numbers (common patterns)
acct_nums = re.findall(r'\b\d{5,10}\b', body_text)
print(f"Potential account numbers: {acct_nums[:20]}")

# Find all divs with meaningful content in the account wrapper
print("\n=== ACCOUNT WRAPPER CONTENT ===")
try:
    wrapper = driver.find_element(By.CSS_SELECTOR, ".account-wrapper__content")
    # Get all direct children
    children = wrapper.find_elements(By.XPATH, "./*")
    print(f"Direct children of account-wrapper__content: {len(children)}")
    for i, child in enumerate(children[:20]):
        cls = child.get_attribute("class") or ""
        tag = child.tag_name
        text = child.text.strip()[:300]
        print(f"\n  Child {i}: <{tag}> class='{cls[:100]}'")
        if text:
            print(f"  Text: {text}")
except Exception as e:
    print(f"No account-wrapper__content: {e}")

# Look for specific FundedNext patterns
patterns_to_find = [
    '[class*="balance"]', '[class*="Balance"]',
    '[class*="equity"]', '[class*="Equity"]',
    '[class*="drawdown"]', '[class*="Drawdown"]',
    '[class*="profit"]', '[class*="Profit"]',
    '[class*="target"]', '[class*="Target"]',
    '[class*="phase"]', '[class*="Phase"]',
    '[class*="challenge"]', '[class*="Challenge"]',
    '[class*="funded"]', '[class*="Funded"]',
    '[class*="step"]', '[class*="Step"]',
    '[class*="stat"]', '[class*="Stat"]',
    '[class*="info"]', '[class*="Info"]',
    '[class*="detail"]', '[class*="Detail"]',
    '[class*="progress"]', '[class*="Progress"]',
    '[class*="metric"]', '[class*="Metric"]',
    '[class*="value"]', '[class*="Value"]',
    '[class*="number"]', '[class*="Number"]',
    '[class*="item"]', '[class*="Item"]',
    '[class*="list"]', '[class*="List"]',
    '[class*="row"]', '[class*="Row"]',
    '[class*="col"]', 
    '[class*="tab-content"]', '[class*="tab-pane"]',
    '[class*="accordion"]', '[class*="collapse"]',
    '[class*="active-account"]',
    '[class*="plan"]', '[class*="Plan"]',
]

print("\n=== PATTERN SEARCH RESULTS ===")
for sel in patterns_to_find:
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, sel)
        meaningful = [e for e in elems if e.text.strip() and len(e.text.strip()) > 5]
        if meaningful:
            print(f"\n{sel}: {len(meaningful)} elements")
            for e in meaningful[:3]:
                cls = e.get_attribute("class") or ""
                print(f"  class='{cls[:80]}' text='{e.text.strip()[:200]}'")
    except:
        pass

# Dump outer HTML of key sections
print("\n=== KEY HTML SNIPPETS ===")
try:
    wrapper = driver.find_element(By.CSS_SELECTOR, ".account-wrapper")
    inner_html = wrapper.get_attribute("innerHTML")
    # Print first 5000 chars of inner HTML
    print(f"\n.account-wrapper innerHTML ({len(inner_html)} chars):")
    print(inner_html[:5000])
except Exception as e:
    print(f"Could not get account-wrapper HTML: {e}")

print(f"\n{'='*60}")
print(f"=== FULL BODY TEXT ===")
print(f"{'='*60}")
print(body_text[:5000])
