"""Test the full Chrome launch + tab opening + CDP attach flow."""
import json, sys, time, urllib.request
sys.path.insert(0, 'trader_companion')
from prop_firm_scrapers import (
    ensure_chrome_debug, TradeifyAccount, MFFUAccount,
    LucidTradingAccount, TopStepAccount, _is_chrome_debug_running
)

print("=== Step 1: Launch Chrome with Tradeify ===")
ensure_chrome_debug('https://app-f.tradeify.co', port=9222)
print(f"Chrome running: {_is_chrome_debug_running()}")

print("\n=== Step 2: Open MFFU tab ===")
ensure_chrome_debug('https://myfundedfutures.com', port=9222)

print("\n=== Step 3: Open Lucid tab ===")
ensure_chrome_debug('https://dash.lucidtrading.com', port=9222)

print("\n=== Step 4: Open TopStep tab ===")
ensure_chrome_debug('https://dashboard.topstep.com', port=9222)

print("\n=== Current tabs ===")
time.sleep(2)
data = json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json').read())
for t in data:
    if t.get('type') == 'page':
        print(f"  {t['url'][:80]}")

print(f"\nTotal page tabs: {sum(1 for t in data if t.get('type')=='page')}")

print("\n=== Step 5: Try attaching scrapers (may fail if not logged in) ===")
for name, cls in [("Tradeify", TradeifyAccount), ("MFFU", MFFUAccount)]:
    try:
        s = cls(debug_port=9222)
        s.login()
        print(f"  {name}: Connected={s.is_connected()}")
        stats = s.get_account_stats()
        print(f"  {name}: Account={stats.get('Account Number', 'N/A')}")
        s.close()
    except Exception as e:
        print(f"  {name}: {e}")

print("\nDone!")
