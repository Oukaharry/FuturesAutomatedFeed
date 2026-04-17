"""
Get FULL account-overview response for real account using account_id parameter.
"""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

port = 9549
opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
driver = webdriver.Chrome(options=opts)

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

# Get full response
result = driver.execute_cdp_cmd("Runtime.evaluate", {
    "expression": f"""
        (async function() {{
            var resp = await fetch('https://api.fundednext.com/api/v1/account-overview?account_id={account_id}', {{
                headers: {{ 'Authorization': 'Bearer {token}', 'Accept': 'application/json' }}
            }});
            return await resp.text();
        }})()
    """,
    "returnByValue": True,
    "awaitPromise": True,
    "timeout": 15000
})
raw = result.get("result", {}).get("value", "{}")
data = json.loads(raw)
print(json.dumps(data, indent=2))
