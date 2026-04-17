"""Get accounts with correct limit."""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)

token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")

base = "https://api.fundednext.com/api/v1"

# Active accounts (limit 20)
print("=== ACTIVE ACCOUNTS (limit=20) ===")
result = driver.execute_script("""
    const resp = await fetch(arguments[0], {
        headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
    });
    return await resp.text();
""", f"{base}/get-accounts?type=active&page=1&limit=20", token)

data = json.loads(result)
print(json.dumps(data, indent=2)[:10000])

# Also try: look at what the "Futures" tab does specifically
# The accounts page has type tabs - CFDs vs Futures
# Maybe there's a filter parameter
print("\n\n=== ACCOUNTS WITH PLATFORM FILTER ===")
for extra in ["&platform=futures", "&platform=tradovate", "&account_type=futures", "&category=futures", "&tab=futures"]:
    url = f"{base}/get-accounts?type=active&page=1&limit=20{extra}"
    result = driver.execute_script("""
        const resp = await fetch(arguments[0], {
            headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
        });
        return {status: resp.status, body: await resp.text()};
    """, url, token)
    status = result.get('status', 0) if result else 0
    if status == 200:
        d = json.loads(result['body'])
        items = d.get('data', {}).get('data', []) if isinstance(d.get('data'), dict) else d.get('data', [])
        print(f"\n  {extra} -> HTTP {status}, items: {len(items) if isinstance(items, list) else 'N/A'}")

print("\n\nDONE")
