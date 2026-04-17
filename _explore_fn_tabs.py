"""Check __NEXT_DATA__, RSC payload, and intercept Futures tab click."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)

token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")

# Navigate to accounts
driver.get("https://app.fundednext.com/accounts")
time.sleep(5)

# 1. Check __NEXT_DATA__
print("=== __NEXT_DATA__ ===")
next_data = driver.execute_script("""
    const el = document.querySelector('#__NEXT_DATA__');
    return el ? el.textContent : 'Not found';
""")
if next_data and next_data != 'Not found':
    try:
        nd = json.loads(next_data)
        print(json.dumps(nd, indent=2, default=str)[:5000])
    except:
        print(next_data[:3000])
else:
    print("No __NEXT_DATA__ found (App Router / RSC)")

# 2. Check RSC inline data
print("\n\n=== RSC / INLINE SCRIPTS ===")
scripts = driver.execute_script("""
    return Array.from(document.querySelectorAll('script'))
        .filter(s => s.textContent.length > 100 && s.textContent.length < 50000)
        .filter(s => s.textContent.includes('account') || s.textContent.includes('FNFT') || s.textContent.includes('login') || s.textContent.includes('tradovate'))
        .map(s => ({type: s.type, id: s.id, text: s.textContent.substring(0, 3000)}));
""")
print(f"Found {len(scripts)} relevant scripts")
for s in scripts:
    print(f"\n  type={s.get('type')}, id={s.get('id')}")
    print(f"  {s.get('text', '')[:2000]}")

# 3. Look at all tab/button elements
print("\n\n=== TABS ON PAGE ===")
tabs = driver.execute_script("""
    // Find tab-like elements
    const tabs = document.querySelectorAll('[role="tab"], .ant-tabs-tab, .ant-segmented-item, [class*="tab"], [class*="Tab"]');
    return Array.from(tabs).map(t => ({
        tag: t.tagName, 
        text: t.textContent.trim().substring(0, 100),
        classes: t.className.substring(0, 200),
        ariaSelected: t.getAttribute('aria-selected'),
        onclick: t.getAttribute('onclick')
    }));
""")
print(f"Found {len(tabs)} tab elements")
for t in tabs:
    print(f"  [{t.get('tag')}] '{t.get('text')}' selected={t.get('ariaSelected')} class={t.get('classes', '')[:100]}")

# 4. Install XHR interceptor BEFORE clicking Futures
print("\n\n=== INSTALLING INTERCEPTOR ===")
driver.execute_script("""
    window._fnCaptures = [];
    const origXHROpen = XMLHttpRequest.prototype.open;
    const origXHRSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._fnUrl = url;
        return origXHROpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            if (this._fnUrl && this._fnUrl.includes('api.fundednext.com')) {
                window._fnCaptures.push({
                    url: this._fnUrl,
                    status: this.status,
                    body: this.responseText.substring(0, 8000)
                });
            }
        });
        return origXHRSend.call(this, ...args);
    };
    
    // Also intercept fetch
    const origFetch = window.fetch;
    window.fetch = async function(input, init) {
        const url = typeof input === 'string' ? input : input.url;
        const resp = await origFetch.call(this, input, init);
        if (url && url.includes('api.fundednext.com')) {
            const clone = resp.clone();
            const text = await clone.text();
            window._fnCaptures.push({url, status: resp.status, body: text.substring(0, 8000)});
        }
        return resp;
    };
""")
print("Interceptor installed")

# 5. Click on "Futures" tab
print("\n=== CLICKING FUTURES TAB ===")
clicked = driver.execute_script("""
    // Find Futures tab text
    const allEls = document.querySelectorAll('*');
    for (const el of allEls) {
        const text = el.textContent.trim();
        if (text === 'Futures' && el.children.length === 0) {
            console.log('Found Futures element:', el.tagName, el.className);
            el.click();
            return {found: true, tag: el.tagName, cls: el.className};
        }
    }
    // Try looking for segmented control items
    const segments = document.querySelectorAll('.ant-segmented-item-label, .ant-radio-button-wrapper');
    for (const seg of segments) {
        if (seg.textContent.trim().includes('Futures')) {
            seg.click();
            return {found: true, tag: seg.tagName, text: seg.textContent.trim()};
        }
    }
    return {found: false};
""")
print(f"Click result: {clicked}")
time.sleep(5)

# 6. Collect intercepted API calls
captures = driver.execute_script("return window._fnCaptures || [];")
print(f"\nIntercepted {len(captures)} API calls after Futures tab click:")
for cap in captures:
    url = cap.get('url', '')
    if any(x in url for x in ['coupon', 'notification', 'alert', 'newsletter', 'survey', 'announcement', 'competition', 'free-trial', 'wrap', 'banner', 'popup', 'eligibility']):
        continue
    print(f"\n{'='*60}")
    print(f"URL: {url[:200]}")
    print(f"Status: {cap.get('status')}")
    body = cap.get('body', '')
    try:
        data = json.loads(body)
        # Check if this contains account info
        data_str = json.dumps(data, default=str)
        if any(x in data_str.lower() for x in ['fnft', 'tradovate', 'account_name', 'server', 'login']):
            print("  *** CONTAINS ACCOUNT DATA ***")
        print(json.dumps(data, indent=2, default=str)[:4000])
    except:
        print(f"  Raw: {body[:1000]}")

# 7. Also get the account cards from the DOM now
print("\n\n=== ACCOUNT CARDS IN DOM ===")
cards = driver.execute_script("""
    const cards = document.querySelectorAll('.dashboard-card, [class*="account-card"], [class*="AccountCard"]');
    return Array.from(cards).map(c => ({
        text: c.textContent.substring(0, 500),
        html: c.innerHTML.substring(0, 1000)
    }));
""")
print(f"Found {len(cards)} card elements")
for card in cards:
    print(f"\n  Text: {card.get('text', '')[:300]}")

print("\n\nDONE")
