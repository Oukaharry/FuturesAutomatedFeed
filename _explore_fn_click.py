"""Minimal: just click Futures tab and read DOM."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)

# Fresh navigation
driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

# Verify page loaded
title = driver.execute_script("return document.title")
print(f"Title: {title}", flush=True)

# Check current state
text = driver.execute_script("return document.body.innerText.substring(0, 500)")
print(f"Initial text: {text[:300]}", flush=True)

# Find and click Futures tab via Selenium (not JS)
try:
    futures_tabs = driver.find_elements(By.XPATH, "//div[contains(@class, 'ant-tabs-tab-btn') and normalize-space(text())='Futures']")
    if futures_tabs:
        print(f"Found {len(futures_tabs)} Futures tab buttons", flush=True)
        futures_tabs[0].click()
        print("Clicked via Selenium", flush=True)
    else:
        # Try broader match
        all_tabs = driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab-btn")
        for t in all_tabs:
            print(f"  Tab: '{t.text}'", flush=True)
            if 'Futures' in t.text:
                t.click()
                print(f"Clicked: {t.text}", flush=True)
                break
except Exception as e:
    print(f"Click error: {e}", flush=True)

time.sleep(5)

# Read result
text2 = driver.execute_script("return document.body.innerText.substring(0, 3000)")
has_error = "Something Went Wrong" in text2
print(f"\nAfter click - Error: {has_error}", flush=True)

if has_error:
    print("Futures tab error. Trying reload approach...", flush=True)
    # Some SPA error -> try going back and retrying
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(5)
    
    # Maybe the tab state is persisted - check if Futures is now selected
    active_tab = driver.execute_script("""
        var active = document.querySelector('.ant-tabs-tab-active .ant-tabs-tab-btn');
        return active ? active.textContent.trim() : 'unknown';
    """)
    print(f"Active tab after reload: {active_tab}", flush=True)
    
    # Get all React chunk sources that might contain account IDs  
    # Check if there's an RSC stream we can parse
    rsc_text = driver.execute_script("""
        // Get all link tags and look for RSC flight data
        var scripts = document.querySelectorAll('script[type]');
        var texts = [];
        for (var i = 0; i < scripts.length; i++) {
            var t = scripts[i].textContent;
            if (t.indexOf('945576089') !== -1 || t.indexOf('FNFT') !== -1) {
                texts.push(t.substring(0, 3000));
            }
        }
        // Also check all elements
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var attrs = all[i].attributes;
            for (var j = 0; j < attrs.length; j++) {
                if (attrs[j].value.indexOf('945576089') !== -1 || attrs[j].value.indexOf('FNFT') !== -1) {
                    texts.push(all[i].outerHTML.substring(0, 1000));
                }
            }
        }
        return texts;
    """)
    print(f"Found {len(rsc_text)} elements with account data", flush=True)
    for t in rsc_text:
        print(f"  {t[:500]}", flush=True)

else:
    print(f"\nFutures page text:\n{text2[:2000]}", flush=True)
    
    # Get dashboard cards
    cards = driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
    print(f"\nDashboard cards: {len(cards)}", flush=True)
    for card in cards:
        print(f"  Card text: {card.text[:300]}", flush=True)

print("\nDONE", flush=True)
