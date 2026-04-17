"""Account linking - v2."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount

# ═══ TRADEIFY ═══
print("=" * 70)
print("TRADEIFY")
print("=" * 70)
try:
    acct = TradeifyAccount(debug_port=9222)
    acct.login()
    
    # Broker credentials
    creds = acct._fetch_json(f"{acct.BASE}/api/dashboard/broker-credentials")
    print(f"Broker creds raw type={type(creds)}")
    print(f"  {json.dumps(creds, default=str)[:800]}")
    
    # Orders  
    r = acct._fetch_json(f"{acct.BASE}/api/dashboard/get-order-list?page=1&page_size=100")
    orders = r.get('data', []) if r else []
    for order in orders:
        ba = order.get('broker_account', {}) or {}
        print(f"\n  Order #{order['id']}:")
        print(f"    broker_account_id={ba.get('broker_account_id')} | tradovate_id={ba.get('account_id')}")
        print(f"    amount=${order.get('amount')} | type={order.get('order_type')}")
    
    # Account overview with all fields
    overview = acct._fetch_json(f"{acct.BASE}/api/dashboard/account-overview?hide_blown_account=false&page=1&page_size=100")
    if overview and overview.get('success'):
        outer = overview.get('data', {})
        items = outer.get('data', []) if isinstance(outer, dict) else []
        for item in items:
            print(f"\n  Overview account: {json.dumps(item, default=str)[:600]}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")

# ═══ FUNDEDNEXT ═══
print("\n" + "=" * 70)
print("FUNDEDNEXT")
print("=" * 70)
try:
    acct = FundedNextCDPAccount(debug_port=9222)
    acct.login()
    
    # Navigate to accounts first for mapping
    acct._navigate_to("/accounts")
    time.sleep(3)
    acct._switch_type_tab("Futures")
    time.sleep(2)
    
    mapping = acct.get_account_mapping()
    print(f"  Mapping ({len(mapping)}):")
    for lid, info in mapping.items():
        print(f"    login={lid} -> tradovate={info.get('tradovate_account_name')}")
        print(f"      {json.dumps(info, default=str)[:300]}")
    
    # Billing
    acct._navigate_to("/billing/billing-history")
    time.sleep(3)
    billing = acct.get_billing_history()
    print(f"\n  Billing ({len(billing)}):")
    for b in billing:
        login = b.get('account_no')
        tradovate = mapping.get(str(login), {}).get('tradovate_account_name', 'UNMAPPED')
        print(f"    login={login} -> tradovate={tradovate} | {b.get('paid_amount')} | {b.get('transition_type')}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══ LUCID ═══
print("\n" + "=" * 70)
print("LUCID")
print("=" * 70)
try:
    acct = LucidTradingAccount(debug_port=9222)
    acct.login()
    user_key = acct._get_user_key()
    
    # Accounts
    summary = acct._fetch_lucid(f"{acct.BASE}/api/users/summary/{user_key}")
    if isinstance(summary, list):
        print(f"  Accounts ({len(summary)}):")
        for s in summary:
            print(f"    {json.dumps(s, default=str)[:400]}")
    
    # Account details
    if isinstance(summary, list):
        for s in summary:
            ak = s.get('accountKey')
            if ak:
                detail = acct._fetch_lucid(f"{acct.BASE}/api/users/accountInfo/{user_key}?accountKey={ak}")
                if detail:
                    print(f"\n  AccountInfo {ak}: {json.dumps(detail, default=str)[:600]}")
    
    # Orders
    orders = acct._fetch_lucid(f"{acct.BASE}/api/users/order-history?userKey={user_key}&limit=50&offset=0")
    print(f"\n  Orders ({len(orders) if orders else 0}):")
    if isinstance(orders, list):
        for o in orders:
            print(f"    {json.dumps(o, default=str)}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()
