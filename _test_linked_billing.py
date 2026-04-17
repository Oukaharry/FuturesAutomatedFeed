"""Test account-linked billing with total fees for all 3 firms."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount
from collections import defaultdict

for name, cls in [("Tradeify", TradeifyAccount), ("FundedNext", FundedNextCDPAccount), ("Lucid Trading", LucidTradingAccount)]:
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    try:
        acct = cls(debug_port=9222)
        acct.login()
        
        # For FundedNext, navigate to accounts first for mapping
        if name == "FundedNext":
            import time
            acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
            time.sleep(5)
            acct._switch_type_tab("Futures")
            time.sleep(3)
        
        # Get account mapping
        mapping = {}
        if hasattr(acct, 'get_account_mapping'):
            mapping = acct.get_account_mapping()
            print(f"  Account Mapping ({len(mapping)}):")
            for key, info in mapping.items():
                print(f"    {key} -> tradovate={info.get('tradovate_account_name')}")
        
        # For FundedNext, navigate to billing page
        if name == "FundedNext":
            acct._js("window.location.href = 'https://app.fundednext.com/billing/billing-history'")
            time.sleep(5)
        
        # Get billing
        billing = acct.get_billing_history()
        print(f"\n  Billing Records ({len(billing)}):")
        
        # Aggregate total fees per account
        totals = defaultdict(float)
        for b in billing:
            acct_no = b.get('account_no', '?')
            login = b.get('login', acct_no)
            amount = b.get('paid_amount_numeric', 0)
            status = b.get('status', '?')
            
            # Resolve to tradovate name via mapping
            tradovate = mapping.get(str(login), {}).get('tradovate_account_name', '')
            resolved = tradovate or acct_no
            
            print(f"    acct={acct_no} | login={login} | tradovate={tradovate or 'N/A'} | "
                  f"{b.get('paid_amount')} | {status} | {b.get('date')} | {b.get('funding_package')}")
            
            if status == "APPROVED" and amount > 0:
                totals[resolved] += amount
        
        print(f"\n  Total Challenge Fees per Account:")
        for acct_key, total in totals.items():
            print(f"    {acct_key}: ${total:.2f}")
        
        acct.disconnect()
    except ConnectionError as e:
        print(f"  Tab not found: {e}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
