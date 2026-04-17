"""Check all FundedNext tabs for accounts"""
import re, sys, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

sys.stdout.reconfigure(encoding='utf-8')

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)
print(f"URL: {driver.current_url}")

# Check each tab combination
tabs_to_check = ["Active", "Inactive", "Breached"]
type_tabs = ["CFDs", "Futures"]

for type_tab in type_tabs:
    # Click type tab
    try:
        btns = driver.find_elements(By.XPATH, f"//*[contains(@class,'ant-tabs')]//div[contains(text(),'{type_tab}')]")
        if not btns:
            btns = driver.find_elements(By.XPATH, f"//*[text()='{type_tab}']")
        for btn in btns:
            if btn.text.strip() == type_tab and btn.is_displayed():
                btn.click()
                time.sleep(2)
                print(f"\n{'='*40}")
                print(f"  TYPE TAB: {type_tab}")
                print(f"{'='*40}")
                break
    except Exception as e:
        print(f"Could not click {type_tab}: {e}")
        continue

    for tab in tabs_to_check:
        try:
            btns = driver.find_elements(By.XPATH, f"//button[text()='{tab}']")
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(2)
                    break
            
            body_text = driver.find_element(By.TAG_NAME, "body").text
            
            # Check for "no account" messages
            has_no_account = "no" in body_text.lower() and "account" in body_text.lower()
            
            # Look for account-like content
            wrapper = None
            try:
                wrapper = driver.find_element(By.CSS_SELECTOR, ".account-wrapper__content")
                wrapper_text = wrapper.text.strip()
            except:
                wrapper_text = "N/A"
            
            print(f"\n  [{type_tab} > {tab}]")
            print(f"  No-account message: {has_no_account}")
            print(f"  Wrapper text: {wrapper_text[:300]}")
            
            # Check for account cards or list items
            potential_accts = driver.find_elements(By.CSS_SELECTOR, "[class*='account-card'], [class*='AccountCard'], [class*='account-item'], [class*='account-list']")
            if potential_accts:
                print(f"  Found {len(potential_accts)} account elements!")
                for a in potential_accts[:5]:
                    print(f"    class='{a.get_attribute('class')[:80]}' text='{a.text[:200]}'")
            
            # Also check for any numeric data that looks like balances
            dollars = re.findall(r'\$[\d,]+\.?\d*', body_text)
            if dollars:
                print(f"  Dollar values: {dollars[:10]}")
                
        except Exception as e:
            print(f"  [{type_tab} > {tab}] Error: {e}")

print("\n\nDone checking all tabs.")
