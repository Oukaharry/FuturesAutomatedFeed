"""Click Futures with script timeout to avoid hangs."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)
d.set_page_load_timeout(15)
d.set_script_timeout(10)

# Navigate fresh
try:
    d.get("https://app.fundednext.com/accounts")
except:
    pass
time.sleep(3)
print(f"On: {d.current_url}", flush=True)

# Click Futures via JS (non-blocking)
try:
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
    print("Clicked Futures", flush=True)
except Exception as e:
    print(f"Click error: {e}", flush=True)

# Wait then try to read
time.sleep(6)

try:
    body = d.execute_script("return document.body.innerText.substring(0, 2000)")
    print(f"Body:\n{body[:1500]}", flush=True)
except Exception as e:
    print(f"Read error: {e}", flush=True)
    # Page might be crashed, try going to a known URL
    try:
        d.get("https://app.fundednext.com/accounts")
    except:
        pass
    time.sleep(3)
    try:
        body = d.execute_script("return document.body.innerText.substring(0, 2000)")
        print(f"After recovery:\n{body[:1000]}", flush=True)
    except Exception as e2:
        print(f"Recovery failed: {e2}", flush=True)

print("DONE", flush=True)
