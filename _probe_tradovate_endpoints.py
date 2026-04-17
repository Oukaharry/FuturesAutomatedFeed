"""Extract Tradovate API structure from the minified JS bundle."""
import requests
import re

MAIN_JS = "https://cdn.tradovate.com/tradovate/scripts/main.ecd7d06c.js"
r = requests.get(MAIN_JS, timeout=15)
js = r.text
print(f"Bundle size: {len(js):,} bytes")

# Find URL construction patterns with template literals or string concat
# Pattern: something + "/v1/" or "api.tradovate" etc.
print("\n=== API HOST PATTERNS ===")
# Look for domain patterns
for pattern in [
    r'["\']([^"\']*tradovateapi\.com[^"\']*)["\']',
    r'["\']([^"\']*\.tradovate\.com[^"\']*api[^"\']*)["\']',
    r'(https?://[^"\'`,\s]+tradovate[^"\'`,\s]*)',
    r'["\']([^"\']*ninjatrader[^"\']*api[^"\']*)["\']',
    r'["\']([^"\']*\.ninjatrader\.[^"\']*)["\']',
]:
    matches = re.findall(pattern, js)
    if matches:
        for m in sorted(set(matches)):
            if len(m) < 120:
                print(f"  {m}")

# Look for host variable assignments
print("\n=== HOST VARIABLE PATTERNS ===")
host_patterns = re.findall(r'(\w*[Hh]ost\w*)\s*[:=]\s*["`\']([^"`\']+)["`\']', js)
for name, val in sorted(set(host_patterns)):
    print(f"  {name} = {val}")

# Look for the actual endpoint construction - e.g., /account/list, /fill/list etc.
print("\n=== ENDPOINT PATHS (from URL construction) ===")
# These are usually constructed as: baseUrl + "/endpoint/action"
ep_patterns = re.findall(r'["\'/]((?:account|order|fill|position|contract|cashBalance|cashBalanceLog|executionReport|marginSnapshot|userAccountAutoLiq|tradingPermission|accountRiskStatus|userProperty|user|command|orderStrategy|alert|adminAlert|contactInfo|product|exchange|spread|currency|orderVersion|contractMaturity|contractGroup|productMargin|chat|replay|md|announcement|marketDataSubscription|clearingHouse)[/\.]\w+)["\']', js)
print(f"  Found {len(set(ep_patterns))} unique endpoint paths:")
for ep in sorted(set(ep_patterns)):
    print(f"    {ep}")

# Look for authentication/token patterns
print("\n=== AUTH PATTERNS ===")
auth_pats = re.findall(r'["\']([^"\']*(?:accesstoken|auth/|/auth|renew|oAuth|Authorization|Bearer)[^"\']*)["\']', js, re.I)
for p in sorted(set(auth_pats)):
    if len(p) < 100:
        print(f"  {p}")

# Check for NinjaTrader API patterns (TopStepX uses NT)
print("\n=== NINJATRADER API PATTERNS ===")
nt_patterns = re.findall(r'["\']([^"\']*ninjatrader[^"\',\s]*(?:api|host|url|endpoint)[^"\']*)["\']', js, re.I)
for p in sorted(set(nt_patterns)):
    print(f"  {p}")

# Look for specific "report" or "accountBalanceHistory" related code
print("\n=== REPORT/HISTORY KEYWORDS IN CONTEXT ===")
# Find "Account Balance History" or "accountReport" in context
for keyword in ["accountBalanceHistory", "balanceHistory", "Account Balance History", 
                "cashBalanceLog", "P&L History", "Account Reports", "accountReport",
                "dailyPnl", "getDailyPnl"]:
    idx = js.find(keyword)
    if idx >= 0:
        context = js[max(0, idx-100):idx+100]
        # Clean up for readability
        print(f"\n  '{keyword}' found at position {idx}:")
        print(f"    ...{context}...")

# Find the CID used by the web trader app itself
print("\n=== EMBEDDED APP CREDENTIALS ===")
# Look near "accesstokenrequest" or "auth" for cid/sec
auth_idx = js.find("accesstokenrequest")
if auth_idx >= 0:
    nearby = js[max(0, auth_idx-500):auth_idx+500]
    cid_match = re.findall(r'cid["\s:]+(\d+)', nearby)
    sec_match = re.findall(r'sec["\s:]+["\']([a-f0-9-]+)["\']', nearby)
    print(f"  Near 'accesstokenrequest':")
    if cid_match: print(f"    cid: {cid_match}")
    if sec_match: print(f"    sec: {sec_match}")
else:
    print("  'accesstokenrequest' not found in bundle - searching alternatives...")
    for term in ["tokenrequest", "accessToken", "authToken"]:
        idx = js.find(term)
        if idx >= 0:
            nearby = js[max(0, idx-300):idx+300]
            print(f"\n  Near '{term}' (at {idx}):")
            print(f"    ...{nearby[:200]}...")
