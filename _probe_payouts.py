"""Quick probe of payout data structure from each firm."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount

for name, cls in [("Tradeify", TradeifyAccount), ("FundedNext", FundedNextCDPAccount), ("Lucid", LucidTradingAccount)]:
    print(f"\n=== {name} Payouts ===")
    try:
        acct = cls(debug_port=9222)
        acct.login()
        payouts = acct.get_payouts()
        print(f"  Count: {len(payouts)}")
        if payouts:
            for i, p in enumerate(payouts[:3]):
                print(f"  [{i}] {json.dumps(p, indent=4, default=str)[:500]}")
        else:
            print("  (empty)")
        acct.disconnect()
    except Exception as e:
        print(f"  ERROR: {e}")
