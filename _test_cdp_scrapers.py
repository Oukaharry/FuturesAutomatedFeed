#!/usr/bin/env python3
"""Quick test of all 4 CDP scrapers."""
import sys
sys.path.insert(0, '.')
from trader_companion.prop_firm_scrapers import TradeifyAccount, LucidTradingAccount, TopStepAccount, MFFUAccount

PORT = 9222

scrapers = [
    ("Tradeify", TradeifyAccount),
    ("Lucid Trading", LucidTradingAccount),
    ("TopStep", TopStepAccount),
    ("MFFU", MFFUAccount),
]

for name, cls in scrapers:
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")
    s = cls(debug_port=PORT)
    try:
        s.login()
        print(f"  Connected: {s.is_connected()}")
        
        stats = s.get_account_stats()
        print(f"  Stats:")
        for k, v in stats.items():
            print(f"    {k}: {v}")
        
        accounts = s.get_all_accounts()
        print(f"  Accounts: {len(accounts)}")
        
        billing = s.get_billing_history()
        print(f"  Billing records: {len(billing)}")
        
        payouts = s.get_payouts()
        print(f"  Payouts: {len(payouts)}")
        
        s.close()
    except ConnectionError as e:
        print(f"  Tab not found: {e}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")
    print()
