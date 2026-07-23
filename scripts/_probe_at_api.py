"""Probe the AlphaTrader REST API for order placement details."""
import requests, re, sys

# Fetch platform page to get JS bundles
r = requests.get("https://futures.alphatrader.com/", timeout=10)
print("Platform:", r.status_code)

# Find JS src files
js_urls = re.findall(r'src="(/[^"]+\.js)"', r.text)
print("JS files found:", js_urls[:8])

# Search JS bundles for API calls related to orders
for url in js_urls[:5]:
    full = "https://futures.alphatrader.com" + url
    try:
        js = requests.get(full, timeout=15).text
        # Look for order-related API calls
        snippets = re.findall(r'.{60}(?:apiv2|/orders?/|t4/trad|placeOrder|submit_order|market.order).{60}', js, re.I)
        if snippets:
            print(f"\n--- {url} ---")
            for s in snippets[:10]:
                print(s)
    except Exception as e:
        print(f"  {url}: {e}")
