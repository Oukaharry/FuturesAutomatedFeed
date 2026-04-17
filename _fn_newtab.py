"""Open new tab, navigate to accounts, click Futures - clean context."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)

# Open new tab for clean context
d.execute_script("window.open('about:blank', '_blank')")
time.sleep(1)
d.switch_to.window(d.window_handles[-1])
print(f"New tab opened. Handles: {len(d.window_handles)}", flush=True)

# Navigate to accounts
d.get("https://app.fundednext.com/accounts")
time.sleep(6)
print(f"Loaded: {d.current_url}", flush=True)

# Check page state
body = d.execute_script("return document.body.innerText.substring(0, 500)")
print(f"Body: {body[:300]}", flush=True)

if "Something Went Wrong" in body:
    print("ERROR on load!", flush=True)
else:
    # Try clicking Futures via Selenium
    try:
        tabs = d.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab")
        for tab in tabs:
            txt = tab.text.strip()
            print(f"  Tab: '{txt}' active={'ant-tabs-tab-active' in tab.get_attribute('class')}", flush=True)
        
        # Click the Futures tab (the parent div, not the inner btn)
        for tab in tabs:
            if tab.text.strip() == "Futures":
                print("Clicking Futures tab...", flush=True)
                tab.click()
                break
        
        time.sleep(6)
        body2 = d.execute_script("return document.body.innerText.substring(0, 2000)")
        has_error = "Something Went Wrong" in body2
        has_fnft = "FNFT" in body2
        print(f"\nAfter Futures click: error={has_error}, FNFT={has_fnft}", flush=True)
        
        if has_error:
            print("Futures tab crashed. Try JS error catch...", flush=True)
            # Get console errors
            logs = d.get_log('browser')
            for log in logs[-10:]:
                print(f"  [{log.get('level')}] {log.get('message', '')[:200]}", flush=True)
        elif has_fnft:
            print(f"SUCCESS! Text:\n{body2[:1500]}", flush=True)
            
            # Get dashboard cards
            cards = d.find_elements(By.CSS_SELECTOR, ".dashboard-card")
            print(f"\nCards: {len(cards)}", flush=True)
            for card in cards:
                print(f"  {card.text[:200]}", flush=True)
                
            # Get React fiber from the card
            fiber = d.execute_script("""
                var cards = document.querySelectorAll('.dashboard-card');
                var results = [];
                for (var i = 0; i < cards.length; i++) {
                    var keys = Object.keys(cards[i]);
                    for (var j = 0; j < keys.length; j++) {
                        if (keys[j].indexOf('__reactFiber') !== -1) {
                            var node = cards[i][keys[j]];
                            for (var k = 0; k < 20 && node; k++) {
                                var p = node.memoizedProps;
                                if (p) {
                                    var s = JSON.stringify(p);
                                    if (s.indexOf('login') !== -1 || s.indexOf('account_id') !== -1 || s.indexOf('945576089') !== -1) {
                                        results.push(s.substring(0, 5000));
                                        break;
                                    }
                                }
                                node = node.return;
                            }
                        }
                    }
                }
                return results;
            """)
            print(f"\nFiber data: {len(fiber)}", flush=True)
            for fd in fiber:
                try:
                    data = json.loads(fd)
                    print(json.dumps(data, indent=2)[:3000], flush=True)
                except:
                    print(fd[:2000], flush=True)
        else:
            print(f"Page text:\n{body2[:1000]}", flush=True)
            
    except Exception as e:
        print(f"Error: {e}", flush=True)

# Close the extra tab
if len(d.window_handles) > 1:
    d.close()
    d.switch_to.window(d.window_handles[0])

print("\nDONE", flush=True)
