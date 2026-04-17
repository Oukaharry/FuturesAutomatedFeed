"""Minimal: open accounts page in new tab with timeout."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)

# Set page load timeout
d.set_page_load_timeout(30)

# Close extra tabs if any
while len(d.window_handles) > 1:
    d.switch_to.window(d.window_handles[-1])
    d.close()
d.switch_to.window(d.window_handles[0])
print(f"Single tab. URL: {d.current_url}", flush=True)

# Navigate to accounts
try:
    d.get("https://app.fundednext.com/accounts")
except Exception as e:
    print(f"Page load timeout (ok): {e}", flush=True)
time.sleep(3)
print(f"On: {d.current_url}", flush=True)

# Check body 
body = d.execute_script("return document.body ? document.body.innerText.substring(0,500) : 'no body'")
print(f"Body:\n{body[:300]}", flush=True)

# Find tabs
tabs_info = d.execute_script("""
    var tabs = document.querySelectorAll('.ant-tabs-tab');
    return Array.from(tabs).map(function(t) {
        return {text: t.textContent.trim(), active: t.className.indexOf('active') !== -1};
    });
""")
print(f"Tabs: {json.dumps(tabs_info)}", flush=True)

# Click Futures
print("Clicking Futures...", flush=True)
d.execute_script("""
    var tabs = document.querySelectorAll('.ant-tabs-tab');
    for (var i = 0; i < tabs.length; i++) {
        if (tabs[i].textContent.trim() === 'Futures') {
            tabs[i].querySelector('.ant-tabs-tab-btn').click();
            return true;
        }
    }
    return false;
""")
time.sleep(6)

body2 = d.execute_script("return document.body ? document.body.innerText.substring(0,2000) : 'no body'")
print(f"\nAfter Futures click:\n{body2[:1500]}", flush=True)

# If we see account cards, get their data
if "FNFT" in body2 or "dashboard-card" in body2 or "Futures Legacy" in body2:
    cards = d.execute_script("""
        return Array.from(document.querySelectorAll('.dashboard-card')).map(function(c) {
            return c.textContent.substring(0, 500);
        });
    """)
    print(f"\nCards: {json.dumps(cards, indent=2)}", flush=True)

print("\nDONE", flush=True)
