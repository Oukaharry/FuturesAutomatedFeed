"""Click Futures tab. Output to file."""
import time, json, traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

out = []
def p(s):
    print(s, flush=True)
    out.append(str(s))

try:
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
    driver = webdriver.Chrome(options=opts)
    p(f"URL: {driver.current_url}")

    token = driver.execute_script("""
        var c = document.cookie.split(';').find(function(c) { return c.trim().indexOf('tokenV1=') === 0; });
        return c ? decodeURIComponent(c.split('=')[1]) : null;
    """)

    driver.get("https://app.fundednext.com/accounts")
    time.sleep(4)
    
    # Install interceptor
    driver.execute_script("""
        window._apiCalls = [];
        var origOpen = XMLHttpRequest.prototype.open;
        var origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            return origOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function() {
            var self = this;
            this.addEventListener('load', function() {
                if (self._url && self._url.indexOf('api.fundednext.com') !== -1) {
                    window._apiCalls.push({url: self._url, status: self.status, body: self.responseText.substring(0, 10000)});
                }
            });
            return origSend.apply(this, arguments);
        };
    """)

    # Click Futures
    driver.execute_script("""
        var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === 'Futures') {
                tabs[i].click();
                break;
            }
        }
    """)
    p("Clicked Futures tab")
    time.sleep(5)

    # Page text
    text = driver.execute_script("return document.body.innerText;")
    p(f"\nPage text (first 3000):\n{text[:3000]}")
    
    # Check intercepted
    captures = driver.execute_script("return window._apiCalls || [];")
    p(f"\nIntercepted {len(captures)} API calls")
    for cap in captures:
        url = cap.get('url', '')
        if any(x in url for x in ['coupon', 'notification', 'alert', 'newsletter', 'survey', 'announcement', 'competition', 'free-trial', 'wrap', 'banner', 'popup', 'eligibility', 'profile']):
            continue
        p(f"\nURL: {url}")
        p(f"Status: {cap.get('status')}")
        body = cap.get('body', '')
        try:
            data = json.loads(body)
            p(json.dumps(data, indent=2, default=str)[:5000])
        except:
            p(f"Raw: {body[:2000]}")

    # Now also check the dashboard cards from DOM for account info
    p("\n\n=== DASHBOARD CARDS ===")
    cards_html = driver.execute_script("""
        var cards = document.querySelectorAll('.dashboard-card');
        var result = [];
        for (var i = 0; i < cards.length; i++) {
            result.push(cards[i].outerHTML.substring(0, 3000));
        }
        return result;
    """)
    p(f"Found {len(cards_html)} dashboard cards")
    for h in cards_html:
        p(h[:2000])

    # Also try to find the React fiber props on account cards
    p("\n\n=== REACT FIBER ON ACCOUNT CARDS ===")
    fiber_data = driver.execute_script("""
        function getFiberProps(el) {
            var keys = Object.keys(el);
            for (var i = 0; i < keys.length; i++) {
                if (keys[i].indexOf('__reactFiber') !== -1 || keys[i].indexOf('__reactInternalInstance') !== -1) {
                    var fiber = el[keys[i]];
                    // Walk up to find memoizedProps with account data
                    var node = fiber;
                    for (var j = 0; j < 20 && node; j++) {
                        var props = node.memoizedProps || {};
                        var propsStr = JSON.stringify(props);
                        if (propsStr.indexOf('FNFT') !== -1 || propsStr.indexOf('tradovate') !== -1 || propsStr.indexOf('login') !== -1) {
                            return props;
                        }
                        node = node.return;
                    }
                }
            }
            return null;
        }
        var cards = document.querySelectorAll('.dashboard-card');
        var results = [];
        for (var i = 0; i < cards.length; i++) {
            var props = getFiberProps(cards[i]);
            if (props) {
                results.push(JSON.stringify(props).substring(0, 5000));
            }
        }
        return results;
    """)
    p(f"Found {len(fiber_data)} fiber results")
    for fd in fiber_data:
        try:
            data = json.loads(fd)
            p(json.dumps(data, indent=2, default=str)[:3000])
        except:
            p(fd[:2000])

except Exception as e:
    traceback.print_exc()
    p(f"ERROR: {e}")

# Write to file
with open("_fn_futures_output.txt", "w") as f:
    f.write("\n".join(out))
p(f"\nOutput written to _fn_futures_output.txt ({len(out)} lines)")
p("DONE")
