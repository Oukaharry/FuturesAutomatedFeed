"""Account linking - FundedNext and Lucid only."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import FundedNextCDPAccount, LucidTradingAccount

# ═══ FUNDEDNEXT ═══
print("FUNDEDNEXT")
print("=" * 70)
try:
    acct = FundedNextCDPAccount(debug_port=9222)
    acct.login()
    
    # Navigate to accounts page first
    acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
    time.sleep(5)
    
    acct._switch_type_tab("Futures")
    time.sleep(3)
    
    mapping = acct.get_account_mapping()
    print(f"Mapping ({len(mapping)}):")
    for lid, info in mapping.items():
        print(f"  login={lid} -> tradovate={info.get('tradovate_account_name')}")
        print(f"    plan={info.get('plan_title')} | balance={info.get('balance')} | starting={info.get('starting_balance')}")

    # Now billing
    acct._js("window.location.href = 'https://app.fundednext.com/billing/billing-history'")
    time.sleep(5)
    
    billing = acct.get_billing_history()
    print(f"\nBilling ({len(billing)}):")
    for b in billing:
        login = b.get('account_no')
        tradovate = mapping.get(str(login), {}).get('tradovate_account_name', 'UNMAPPED')
        print(f"  login={login} -> tradovate={tradovate} | {b.get('paid_amount')} | {b.get('transition_type')}")
    
    acct.disconnect()
except Exception as e:
    print(f"ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══ LUCID ═══
print("\n" + "=" * 70)
print("LUCID")
print("=" * 70)
try:
    acct = LucidTradingAccount(debug_port=9222)
    acct.login()
    user_key = acct._get_user_key()
    
    # Summary has account names
    summary = acct._fetch_lucid(f"{acct.BASE}/api/users/summary/{user_key}")
    if isinstance(summary, list):
        print(f"Accounts ({len(summary)}):")
        for s in summary:
            print(f"  name={s.get('accountName')} | plan={s.get('planCode')} | status={s.get('status')}")
            # Show all keys
            for k in sorted(s.keys()):
                v = s[k]
                if isinstance(v, (str, int, float, bool)) or v is None:
                    print(f"    {k}: {v}")
    
    # Account detail - check for Tradovate info
    if isinstance(summary, list):
        for s in summary:
            ak = s.get('accountKey')
            if ak:
                detail = acct._fetch_lucid(f"{acct.BASE}/api/users/accountInfo/{user_key}?accountKey={ak}")
                if detail and isinstance(detail, dict):
                    print(f"\nAccountInfo {ak}:")
                    for k in sorted(detail.keys()):
                        v = detail[k]
                        if isinstance(v, (str, int, float, bool)) or v is None:
                            print(f"  {k}: {v}")
                        elif isinstance(v, dict):
                            print(f"  {k}: {json.dumps(v, default=str)[:200]}")
    
    # Orders
    orders = acct._fetch_lucid(f"{acct.BASE}/api/users/order-history?userKey={user_key}&limit=50&offset=0")
    print(f"\nOrders ({len(orders) if orders else 0}):")
    if isinstance(orders, list):
        for o in orders:
            print(f"  {json.dumps(o, default=str)}")
    
    acct.disconnect()
except Exception as e:
    print(f"ERROR: {e}")
    import traceback; traceback.print_exc()
