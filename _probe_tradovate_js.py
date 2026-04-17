"""Extract API endpoints and auth flow from Tradovate main.js bundle."""
import requests
import re
import json

# The main app bundle
MAIN_JS = "https://cdn.tradovate.com/tradovate/scripts/main.ecd7d06c.js"
CHUNK_JS = "https://cdn.tradovate.com/tradovate/scripts/7448.f9f8f421.js"

for name, url in [("main.js", MAIN_JS), ("chunk.js", CHUNK_JS)]:
    print(f"\n{'='*60}")
    print(f"Analyzing {name} ({url})")
    print('='*60)
    
    r = requests.get(url, timeout=15)
    js = r.text
    print(f"  Size: {len(js):,} bytes")
    
    # Find API base URLs
    api_urls = re.findall(r'["\']https?://[^"\']*tradovateapi[^"\']*["\']', js)
    print(f"\n  API Base URLs ({len(set(api_urls))}):")
    for u in sorted(set(api_urls)):
        print(f"    {u}")
    
    # Find WebSocket URLs
    ws_urls = re.findall(r'["\']wss?://[^"\']*tradovate[^"\']*["\']', js)
    print(f"\n  WebSocket URLs ({len(set(ws_urls))}):")
    for u in sorted(set(ws_urls)):
        print(f"    {u}")
    
    # Find REST endpoint paths (e.g., "account/list", "fill/list")
    rest_paths = re.findall(r'["\'](\w+/(?:list|item|items|find|suggest|ldeps|deps|create|update|delete|activate|deactivate)[^"\']*)["\']', js)
    print(f"\n  REST Endpoint Paths ({len(set(rest_paths))}):")
    for p in sorted(set(rest_paths)):
        print(f"    {p}")
    
    # Find specific endpoint patterns we care about
    history_patterns = re.findall(r'["\']([^"\']*(?:history|balance|fill|report|pnl|cashBalance|execution|trade)[^"\']*)["\']', js, re.I)
    print(f"\n  History/Balance/Fill Related ({len(set(history_patterns))}):")
    for p in sorted(set(history_patterns)):
        if len(p) < 80 and not p.endswith('.css') and not p.endswith('.png'):
            print(f"    {p}")
    
    # Find auth-related code
    auth_patterns = re.findall(r'["\']([^"\']*(?:accesstoken|auth/|login|renew|oAuth)[^"\']*)["\']', js, re.I)
    print(f"\n  Auth Endpoints ({len(set(auth_patterns))}):")
    for p in sorted(set(auth_patterns)):
        if len(p) < 100:
            print(f"    {p}")
    
    # Find the cid/sec (app credentials embedded in the web app)
    cid_patterns = re.findall(r'cid["\s:]+(\d+)', js)
    sec_patterns = re.findall(r'sec["\s:]+["\']([a-f0-9-]+)["\']', js)
    if cid_patterns:
        print(f"\n  Embedded CID values: {sorted(set(cid_patterns))}")
    if sec_patterns:
        print(f"  Embedded SEC values: {sorted(set(sec_patterns))}")
    
    # Look for account report / balance history specific endpoints
    report_patterns = re.findall(r'["\']([^"\']*(?:report|Account.*Balance|Balance.*History|accountReport|dailyPnl|cashBalanceLog|marginLog)[^"\']*)["\']', js, re.I)
    print(f"\n  Report/AccountBalance Related ({len(set(report_patterns))}):")
    for p in sorted(set(report_patterns)):
        if len(p) < 100:
            print(f"    {p}")

    # Find all unique path segments that look like API endpoints
    all_endpoints = re.findall(r'["\']([a-zA-Z]+/[a-zA-Z]+(?:/[a-zA-Z]+)?)["\']', js)
    # Filter to likely Tradovate API endpoints
    likely_api = set()
    known_prefixes = {'account', 'order', 'fill', 'position', 'contract', 'cashBalance', 
                      'cashBalanceLog', 'executionReport', 'marginSnapshot', 'userProperty',
                      'tradingPermission', 'user', 'auth', 'contactInfo', 'orderStrategy',
                      'accountRiskStatus', 'userAccountAutoLiq', 'adminAlert', 'alert',
                      'command', 'product', 'exchange', 'spread', 'currency', 'orderVersion'}
    for ep in all_endpoints:
        prefix = ep.split('/')[0]
        if prefix.lower() in {p.lower() for p in known_prefixes}:
            likely_api.add(ep)
    
    print(f"\n  All Likely API Endpoints ({len(likely_api)}):")
    for p in sorted(likely_api):
        print(f"    {p}")
