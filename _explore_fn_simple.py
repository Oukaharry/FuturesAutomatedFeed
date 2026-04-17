"""Simple: connect and check __NEXT_DATA__ + find tabs."""
import time, json, traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

try:
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
    driver = webdriver.Chrome(options=opts)
    print(f"URL: {driver.current_url}", flush=True)

    # Navigate to accounts
    driver.get("https://app.fundednext.com/accounts")
    time.sleep(4)
    print(f"After nav: {driver.current_url}", flush=True)

    # Check __NEXT_DATA__
    nd = driver.execute_script("var el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent.substring(0,200) : 'NONE';")
    print(f"__NEXT_DATA__: {nd}", flush=True)

    # Get all text on page that mentions FNFT or account
    text = driver.execute_script("return document.body.innerText.substring(0, 5000);")
    print(f"\nPage text:\n{text[:3000]}", flush=True)

    # Check tabs/buttons
    tabs = driver.execute_script("""
        var results = [];
        var els = document.querySelectorAll('span, div, button, a, label');
        for (var i = 0; i < els.length; i++) {
            var t = els[i].textContent.trim();
            if ((t === 'Futures' || t === 'CFDs' || t === 'CFD') && els[i].children.length <= 1) {
                results.push({tag: els[i].tagName, text: t, cls: els[i].className.substring(0,100)});
            }
        }
        return results;
    """)
    print(f"\nTab elements: {json.dumps(tabs, indent=2)}", flush=True)

except Exception as e:
    traceback.print_exc()
    print(f"ERROR: {e}", flush=True)

print("DONE", flush=True)
