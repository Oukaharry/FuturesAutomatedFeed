"""Check FundedNext breached/inactive accounts."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import FundedNextCDPAccount

acct = FundedNextCDPAccount(debug_port=9222)
acct.login()

# Navigate to accounts page
acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
time.sleep(5)
acct._switch_type_tab("Futures")
time.sleep(3)

for tab_name in ["Inactive", "Breached"]:
    print(f"\n=== Clicking '{tab_name}' tab ===")
    clicked = acct._js(f"""
    (function() {{
        var tabs = document.querySelectorAll('[role="tab"], .ant-tabs-tab, button');
        for (var i = 0; i < tabs.length; i++) {{
            if (tabs[i].innerText.trim().toLowerCase().includes('{tab_name.lower()}')) {{
                tabs[i].click();
                return 'clicked: ' + tabs[i].innerText.trim();
            }}
        }}
        return 'not found';
    }})()
    """)
    print(f"  Click result: {clicked}")
    time.sleep(3)

    # Get all dashboard card data
    raw = acct._js("""
    (function() {
        var cards = document.querySelectorAll('.dashboard-card');
        var results = [];
        for (var i = 0; i < cards.length; i++) {
            var fiber = null;
            var keys = Object.keys(cards[i]);
            for (var j = 0; j < keys.length; j++) {
                if (keys[j].startsWith('__reactFiber$') || keys[j].startsWith('__reactInternalInstance$')) {
                    fiber = cards[i][keys[j]];
                    break;
                }
            }
            if (!fiber) continue;
            var node = fiber;
            for (var depth = 0; depth < 30; depth++) {
                if (node && node.memoizedProps && node.memoizedProps.account) break;
                node = node.return;
            }
            if (node && node.memoizedProps && node.memoizedProps.account) {
                var a = node.memoizedProps.account;
                results.push({
                    login: a.login,
                    tradovate_name: a.tradovateAccount,
                    status: a.status,
                    planTitle: a.planTitle,
                    currentBalance: a.currentBalance,
                    startingBalance: a.startingBalance,
                    breached: a.breached,
                    createdAt: a.createdAt
                });
            }
        }
        return JSON.stringify(results, null, 2);
    })()
    """)

    if raw:
        data = json.loads(raw)
        if data:
            for card in data:
                print(f"  {json.dumps(card, indent=4)}")
        else:
            print("  No cards found")
    else:
        print("  No data")

    # Also get page text snippet
    text = acct._js("document.querySelector('.ant-tabs-tabpane-active')?.innerText?.substring(0, 1000) || document.body.innerText.substring(0, 500)")
    print(f"  Page snippet: {text[:300] if text else 'none'}")

acct.disconnect()
