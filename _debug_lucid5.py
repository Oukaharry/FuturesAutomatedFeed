import json, sys
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import LucidTradingAccount

s = LucidTradingAccount(debug_port=9222)
s.login()

token = s._js("localStorage.getItem('auth_token')")
user_key = s._js("localStorage.getItem('userKey')")
base = "https://dash.lucidtrading.com/api"

# Test the REAL endpoints discovered from interception
endpoints = [
    f"/users/summary/{user_key}",
    "/accounts/plans",
    f"/users/wp-profile?userKey={user_key}",
    "/users/otp",
]

print("=== Testing real Lucid endpoints with Bearer ===")
for ep in endpoints:
    url = f"{base}{ep}"
    result = s._fetch_json_bearer(url, token)
    txt = json.dumps(result, indent=2)[:500] if result else "None"
    print(f"\n{ep}:\n{txt}")

# Also test with plain fetch (no Bearer) to see if it works with cookies only
print("\n\n=== Testing with cookies only (no Bearer) ===")
for ep in [f"/users/summary/{user_key}", "/users/otp"]:
    url = f"{base}{ep}"
    result = s._fetch_json(url)
    txt = json.dumps(result, indent=2)[:500] if result else "None"
    print(f"\n{ep}:\n{txt}")

# Check what XHR sends - maybe it uses a custom header
print("\n\n=== Check how XHR sends auth ===")
auth_check = s._js("""
    (() => {
        // Intercept the next XHR to see headers
        const origSend = XMLHttpRequest.prototype.send;
        const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
        const headers = [];
        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
            headers.push({name, value: value.substring(0, 50)});
            return origSetHeader.call(this, name, value);
        };
        
        // Make a test request
        const xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/users/otp', false);
        // The app's interceptor should add auth headers
        xhr.send();
        
        XMLHttpRequest.prototype.setRequestHeader = origSetHeader;
        return JSON.stringify({headers, status: xhr.status, response: xhr.responseText.substring(0, 200)});
    })()
""")
print("XHR auth inspection:", auth_check)

s.close()
