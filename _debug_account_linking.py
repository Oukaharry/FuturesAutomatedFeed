"""Explore account linking: what Tradovate account info is in each firm's data."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount

# ═══════════════════════════════════════════════
# TRADEIFY: broker_account in order data
# ═══════════════════════════════════════════════
print("=" * 70)
print("TRADEIFY: Account Linking")
print("=" * 70)
try:
    acct = TradeifyAccount(debug_port=9222)
    acct.login()
    
    # Get orders with full broker_account data
    r = acct._fetch_json(f"{acct.BASE}/api/dashboard/get-order-list?page=1&page_size=100")
    if r and r.get('data'):
        for order in r['data']:
            ba = order.get('broker_account', {})
            plan = order.get('plan', {}) or {}
            print(f"  Order #{order['id']}:")
            print(f"    broker_account_id: {ba.get('broker_account_id')}")
            print(f"    account_id (tradovate): {ba.get('account_id')}")
            print(f"    funded_status: {ba.get('funded_status')}")
            print(f"    account_status: {ba.get('account_status')}")
            print(f"    account_type: {ba.get('account_type')}")
            print(f"    initial_balance: {ba.get('initial_balance')}")
            print(f"    amount paid: {order.get('amount')}")
            print(f"    order_type: {order.get('order_type')}")
    
    # Also check account-overview for Tradovate account names
    print("\n  Account Overview:")
    overview = acct._fetch_json(f"{acct.BASE}/api/dashboard/account-overview?hide_blown_account=false&page=1&page_size=100")
    if overview and overview.get('success'):
        outer = overview.get('data', {})
        items = outer.get('data', []) if isinstance(outer, dict) else []
        for item in items:
            print(f"    Account: {json.dumps(item, default=str)[:400]}")
    
    # Check broker-credentials for Tradovate mapping
    print("\n  Broker Credentials:")
    creds = acct._fetch_json(f"{acct.BASE}/api/dashboard/broker-credentials")
    if creds:
        if isinstance(creds, dict):
            data = creds.get('data', creds)
            print(f"    {json.dumps(data, default=str)[:500]}")
        elif isinstance(creds, list):
            for c in creds[:3]:
                print(f"    {json.dumps(c, default=str)[:300]}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══════════════════════════════════════════════
# FUNDEDNEXT: account mapping (login -> tradovate)
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("FUNDEDNEXT: Account Linking")
print("=" * 70)
try:
    acct = FundedNextCDPAccount(debug_port=9222)
    acct.login()
    
    # get_account_mapping maps login IDs to Tradovate account names
    mapping = acct.get_account_mapping()
    print(f"  Account mapping ({len(mapping)} accounts):")
    for login_id, info in mapping.items():
        print(f"    login={login_id} -> tradovate={info.get('tradovate_account_name')}")
        print(f"      plan: {info.get('plan_title')}, balance: {info.get('balance')}")
        print(f"      starting_balance: {info.get('starting_balance')}")
        print(f"      breached: {info.get('breached')}")
    
    # Now get billing and see if login matches
    billing = acct.get_billing_history()
    print(f"\n  Billing ({len(billing)} records):")
    for b in billing:
        acct_no = b.get('account_no')
        tradovate = mapping.get(acct_no, {}).get('tradovate_account_name', 'UNMAPPED')
        print(f"    acct={acct_no} -> tradovate={tradovate} | {b.get('paid_amount')} | {b.get('funding_package')} | {b.get('transition_type')}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══════════════════════════════════════════════
# LUCID: check if we can link orders to accounts
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("LUCID: Account Linking")
print("=" * 70)
try:
    acct = LucidTradingAccount(debug_port=9222)
    acct.login()
    
    user_key = acct._get_user_key()
    
    # Get accounts
    summary = acct._fetch_lucid(f"{acct.BASE}/api/users/summary/{user_key}")
    if isinstance(summary, list):
        print(f"  Accounts ({len(summary)}):")
        for s in summary:
            print(f"    name={s.get('accountName')} | key={s.get('accountKey')} | "
                  f"type={s.get('planCode')} | status={s.get('status')} | "
                  f"bal={s.get('accountBalance')}")
    
    # Get account details for Tradovate info
    print("\n  Account details:")
    if isinstance(summary, list):
        for s in summary:
            acct_key = s.get('accountKey')
            if acct_key:
                detail = acct._fetch_lucid(f"{acct.BASE}/api/users/accountInfo/{user_key}?accountKey={acct_key}")
                if detail:
                    print(f"    {acct_key}: {json.dumps(detail, default=str)[:500]}")
    
    # Get billing
    orders = acct._fetch_lucid(f"{acct.BASE}/api/users/order-history?userKey={user_key}&limit=50&offset=0")
    if isinstance(orders, list):
        print(f"\n  Orders ({len(orders)}):")
        for o in orders:
            print(f"    #{o.get('orderId')} | {o.get('productNames')} | ${o.get('totalAmount')} | {o.get('status')}")
            # Full order data
            print(f"    FULL: {json.dumps(o, default=str)}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()
