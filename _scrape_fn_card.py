"""Scrape FundedNext account card DOM structure"""
import re, sys, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

sys.stdout.reconfigure(encoding='utf-8')

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"URL: {driver.current_url}")

# Click Futures tab first
tabs = driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab")
for t in tabs:
    if t.text.strip() == "Futures":
        t.click()
        time.sleep(2)
        break

# Click Active
buttons = driver.find_elements(By.CSS_SELECTOR, ".account-wrapper__create-account button")
for b in buttons:
    if b.text.strip() == "Active":
        b.click()
        time.sleep(2)
        break

# Now get the account wrapper content
wrapper = driver.find_element(By.CSS_SELECTOR, ".account-wrapper__content")
print(f"\n=== WRAPPER TEXT ===\n{wrapper.text[:2000]}")

# Get all children recursively with classes
children = wrapper.find_elements(By.XPATH, ".//*")
print(f"\nTotal descendant elements: {len(children)}")

# Find meaningful elements with text
print("\n=== ELEMENTS WITH TEXT ===")
seen_texts = set()
for el in children:
    text = el.text.strip()
    tag = el.tag_name
    cls = (el.get_attribute("class") or "")[:120]
    if text and len(text) > 3 and text not in seen_texts and tag not in ('svg', 'path'):
        seen_texts.add(text)
        if len(text) < 200:
            print(f"  <{tag}> class='{cls}' => {repr(text)}")

# Get the account card innerHTML
print("\n=== ACCOUNT CARD SEARCH ===")
# The card appears to be a div with the account info
# Look for elements containing the account ID
acct_elements = driver.find_elements(By.XPATH, "//*[contains(text(),'FNFT')]")
for el in acct_elements[:5]:
    tag = el.tag_name
    cls = (el.get_attribute("class") or "")[:120]
    parent = el.find_element(By.XPATH, "..")
    grandparent = parent.find_element(By.XPATH, "..")
    ggparent = grandparent.find_element(By.XPATH, "..")
    print(f"\n  FNFT element: <{tag}> class='{cls}'")
    print(f"  Parent: <{parent.tag_name}> class='{(parent.get_attribute('class') or '')[:120]}'")
    print(f"  Grandparent: <{grandparent.tag_name}> class='{(grandparent.get_attribute('class') or '')[:120]}'")
    print(f"  Great-grandparent: <{ggparent.tag_name}> class='{(ggparent.get_attribute('class') or '')[:120]}'")
    
    # Get the card-level element (great-grandparent likely)
    for ancestor in [parent, grandparent, ggparent]:
        atext = ancestor.text.strip()
        if 'Balance' in atext and 'Equity' in atext:
            print(f"\n  === CARD ELEMENT FOUND ===")
            print(f"  Tag: <{ancestor.tag_name}>")
            print(f"  Class: {(ancestor.get_attribute('class') or '')[:200]}")
            print(f"  Text:\n{atext[:500]}")
            # Get innerHTML
            html = ancestor.get_attribute("innerHTML")
            print(f"\n  innerHTML ({len(html)} chars):\n{html[:3000]}")
            break

# Also look for "Balance" and "Equity" labeled elements
print("\n=== BALANCE/EQUITY ELEMENTS ===")
for label in ["Balance", "Equity", "Server Type", "Account Type"]:
    els = driver.find_elements(By.XPATH, f"//*[contains(text(),'{label}')]")
    for el in els[:3]:
        tag = el.tag_name
        cls = (el.get_attribute("class") or "")[:100]
        text = el.text.strip()[:200]
        print(f"  '{label}' => <{tag}> class='{cls}' text='{text}'")

# Dollar values on page
body_text = driver.find_element(By.TAG_NAME, "body").text
dollars = re.findall(r'-?\$[\d,]+\.?\d*', body_text)
print(f"\nDollar values: {dollars}")

# Account numbers
acct_nums = re.findall(r'FNFT\w+', body_text)
print(f"Account IDs: {acct_nums}")

print("\nDone!")
