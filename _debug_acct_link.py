"""Account linking - run each firm separately to avoid tab conflicts."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount

# ═══ TRADEIFY ═══
print("=" * 70)
print("TRADEIFY: Account Linking")
print("=" * 70)
try:
    acct = TradeifyAccount(debug_port=9222)
    acct.login()
    
    # Order list has broker_account with Tradovate account_id
    r = acct._fetch_json(f"{acct.BASE}/api/dashboard/get-order-list?page=1&page_size=100")
    orders = r.get('data', []) if r else []
    
    # Broker credentials has Tradovate login names
    creds = acct._fetch_json(f"{acct.BASE}/api/dashboard/broker-credentials")
    cred_data = creds.get('data', []) if isinstance(creds, dict) else []
    
    print(f"\n  Broker credentials ({len(cred_data)}):")
    cred_map = {}
    for c in cred_data:
        print(f"    tradovate_acct={c.get('account_number')} | name={c.get('name')} | broker={c.get('broker')}")
        cred_map[c.get('name', '')] = c.get('account_number', '')
    
    print(f"\n  Orders ({len(orders)}) with broker_account linking:")
    for order in orders:
        ba = order.get('broker_account', {}) or {}
        broker_id = ba.get('broker_account_id', '')
        tradovate_id = ba.get('account_id', '')
        amount = order.get('amount', '?')
        otype = order.get('order_type', '?')
        # The broker_account_id format: TDFYSL50865444931
        # The broker credentials name: TDFYU99556146* 
        # Can we match? Let's check account-overview for more info
        print(f"    order={order['id']} | broker_account_id={broker_id} | "
              f"tradovate_account_id={tradovate_id} | amount=${amount} | type={otype}")

    # Account overview has the full mapping
    overview = acct._fetch_json(f"{acct.BASE}/api/dashboard/account-overview?hide_blown_account=false&page=1&page_size=100")
    if overview and overview.get('success'):
        outer = overview.get('data', {})
        items = outer.get('data', []) if isinstance(outer, dict) else []
        print(f"\n  Account Overview ({len(items)}):")
        for item in items:
            print(f"    id={item.get('id')} | account_id={item.get('account_id')} | "
                  f"broker_id={item.get('broker_account_id')} | type={item.get('account_type')} | "
                  f"status={item.get('account_status')} | funded={item.get('funded_status')}")
            # Check for tradovate account name or credential link
            if 'credential' in item or 'credential_id' in item:
                print(f"      credential: {item.get('credential', item.get('credential_id'))}")
            # Print any key with 'trad' or 'cred' or 'name'
            for k, v in item.items():
                if any(t in k.lower() for t in ['trad', 'cred', 'name', 'login']):
                    print(f"      {k}: {v}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══ FUNDEDNEXT ═══
print("\n" + "=" * 70)
print("FUNDEDNEXT: Account Linking")
print("=" * 70)
try:
    acct = FundedNextCDPAccount(debug_port=9222)
    acct.login()
    
    # First navigate to accounts page for the mapping
    acct._navigate_to("/accounts")
    time.sleep(2)
    acct._switch_type_tab("Futures")
    time.sleep(2)
    
    mapping = acct.get_account_mapping()
    print(f"  Account mapping ({len(mapping)}):")
    for login_id, info in mapping.items():
        print(f"    login={login_id} -> tradovate={info.get('tradovate_account_name')}")
        print(f"      plan: {info.get('plan_title')}, balance: {info.get('balance')}, "
              f"starting: {info.get('starting_balance')}, breached: {info.get('breached')}")
    
    # Navigate to billing page for DOM scrape
    acct._navigate_to("/billing/billing-history")
    time.sleep(3)
    
    billing = acct.get_billing_history()
    print(f"\n  Billing ({len(billing)}):")
    for b in billing:
        acct_no = b.get('account_no')
        trado = mapping.get(str(acct_no), {}).get('tradovate_account_name', 'UNMAPPED')
        print(f"    login={acct_no} -> tradovate={trado} | {b.get('paid_amount')} | "
              f"{b.get('funding_package')} | {b.get('transition_type')}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ═══ LUCID ═══
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
                  f"type={s.get('planCode')} | status={s.get('status')}")
            # Show ALL keys for potential Tradovate linking
            for k, v in s.items():
                if any(t in k.lower() for t in ['trad', 'login', 'cred', 'platform', 'broker']):
                    print(f"      {k}: {v}")
    
    # Account detail for each account
    if isinstance(summary, list):
        for s in summary:
            acct_key = s.get('accountKey')
            if acct_key:
                detail = acct._fetch_lucid(f"{acct.BASE}/api/users/accountInfo/{user_key}?accountKey={acct_key}")
                if detail:
                    print(f"\n  AccountInfo for {acct_key}:")
                    if isinstance(detail, dict):
                        for k, v in detail.items():
                            if isinstance(v, (str, int, float, bool)) or v is None:
                                print(f"    {k}: {v}")
                            elif isinstance(v, dict) and len(str(v)) < 200:
                                print(f"    {k}: {v}")
    
    # Orders
    orders = acct._fetch_lucid(f"{acct.BASE}/api/users/order-history?userKey={user_key}&limit=50&offset=0")
    if isinstance(orders, list):
        print(f"\n  Orders ({len(orders)}):")
        for o in orders:
            print(f"    FULL: {json.dumps(o, default=str)}")
    
    acct.disconnect()
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()
