"""Check FundedNext accounts - are there multiple?"""
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

# Dump ALL dashboard cards including hidden/blown
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
        if (!fiber) { results.push({error: 'no fiber for card ' + i}); continue; }
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

print("=== ALL DASHBOARD CARDS ===")
if raw:
    data = json.loads(raw)
    for i, card in enumerate(data):
        print(f"\nCard {i}: {json.dumps(card, indent=2)}")
else:
    print("No data returned")

# Also check ALL accounts dropdown/filter
raw2 = acct._js("""
(function() {
    // Check if there's a filter or dropdown for account status
    var allText = document.body.innerText;
    // Look for number of accounts mentioned
    var m = allText.match(/showing\\s+(\\d+)/i) || allText.match(/(\\d+)\\s+account/i);
    return JSON.stringify({
        match: m ? m[0] : null, 
        bodySnippet: allText.substring(0, 2000)
    });
})()
""")
print("\n=== PAGE TEXT ===")
if raw2:
    info = json.loads(raw2)
    print(info.get("bodySnippet", ""))

acct.disconnect()
