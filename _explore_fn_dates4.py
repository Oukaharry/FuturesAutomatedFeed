"""
Final check: try to find any endpoint with real account dates.
"""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

port = 9549
opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
driver = webdriver.Chrome(options=opts)

login = 945576089
account_id = 3227488

# Get token
token_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var c = document.cookie.split(';').find(function(c) {
            return c.trim().indexOf('tokenV1=') === 0;
        });
        c ? decodeURIComponent(c.split('=')[1]) : null;
    """,
    "returnByValue": True,
    "timeout": 5000
})
token = token_result.get("result", {}).get("value")

endpoints = [
    # Trading overview with various types
    f"trading-overview?login={login}&type=challenge",
    f"trading-overview?login={login}&type=evaluation",
    f"trading-overview?login={login}&type=active",
    f"trading-overview?login={login}&type=1",
    f"trading-overview?login={login}&type=2",
    # Trading history / journal
    f"trading-history?login={login}",
    f"trade-history?login={login}",
    f"trade-journal?login={login}",
    f"trading-journal?login={login}&page=1",
    f"trades?login={login}",
    f"get-trades?login={login}",
    # Account-specific
    f"account-overview?login={login}&type=futures",
    f"account-overview?account_id={account_id}",
    f"account-overview?id={account_id}",
    f"get-trading-cycle?login={login}",
    f"trading-cycle?login={login}",
    f"account-metrics?login={login}",
    f"account-metrics?account_id={account_id}",
    # Objectives
    f"objectives?login={login}",
    f"get-objectives?login={login}",
    f"challenge-objectives?login={login}",
]

print("=== PROBING API ENDPOINTS ===")
for ep in endpoints:
    url = f"https://api.fundednext.com/api/v1/{ep}"
    result = driver.execute_cdp_cmd("Runtime.evaluate", {
        "expression": f"""
            (async function() {{
                try {{
                    var resp = await fetch('{url}', {{
                        headers: {{ 'Authorization': 'Bearer {token}', 'Accept': 'application/json' }}
                    }});
                    var text = await resp.text();
                    return JSON.stringify({{s: resp.status, b: text.substring(0, 400)}});
                }} catch(e) {{
                    return JSON.stringify({{error: e.toString()}});
                }}
            }})()
        """,
        "returnByValue": True,
        "awaitPromise": True,
        "timeout": 10000
    })
    raw = result.get("result", {}).get("value", "{}")
    data = json.loads(raw)
    status = data.get("s", "?")
    body = data.get("b", "")
    # Only show non-404 responses
    if status != 404:
        print(f"\n  [{status}] {ep}")
        print(f"    {body[:300]}")

# Also navigate to accounts page and check if there's a "view" link per card
print("\n\n=== CHECKING ACCOUNT CARD BUTTONS/LINKS ===")
driver.get("https://app.fundednext.com/accounts")
time.sleep(3)

# Click Futures tab
driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === 'Futures') tabs[i].click();
        }
    """,
    "returnByValue": True,
    "timeout": 5000
})
time.sleep(3)

# Check for clickable elements on account cards
buttons_result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": """
        var cards = document.querySelectorAll('.dashboard-card');
        var info = [];
        for (var i = 0; i < cards.length; i++) {
            var btns = cards[i].querySelectorAll('button, a, [role=button]');
            var btnInfo = [];
            for (var j = 0; j < btns.length; j++) {
                btnInfo.push({
                    tag: btns[j].tagName,
                    text: btns[j].textContent.trim().substring(0, 60),
                    href: btns[j].href || '',
                    className: btns[j].className.substring(0, 60)
                });
            }
            info.push({cardIndex: i, buttons: btnInfo});
        }
        JSON.stringify(info, null, 2);
    """,
    "returnByValue": True,
    "timeout": 5000
})
braw = buttons_result.get("result", {}).get("value", "[]")
bdata = json.loads(braw)
for card in bdata:
    print(f"\nCard {card['cardIndex']}:")
    for btn in card.get('buttons', []):
        print(f"  {btn['tag']}: '{btn['text']}' href={btn['href']} class={btn['className'][:40]}")

print("\nDone!")
