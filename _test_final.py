"""Final verification: per-firm totals + FundedNext separation."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import TradeifyAccount, FundedNextCDPAccount, LucidTradingAccount

for name, cls in [("Tradeify", TradeifyAccount), ("FundedNext", FundedNextCDPAccount), ("Lucid", LucidTradingAccount)]:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    try:
        acct = cls(debug_port=9222)
        acct.login()

        if name == "FundedNext":
            acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
            time.sleep(5)
            acct._switch_type_tab("Futures")
            time.sleep(3)

        mapping = acct.get_account_mapping() if hasattr(acct, 'get_account_mapping') else {}

        if name == "FundedNext":
            acct._js("window.location.href = 'https://app.fundednext.com/billing/billing-history'")
            time.sleep(5)

        billing = acct.get_billing_history()
        payouts = acct.get_payouts() if hasattr(acct, 'get_payouts') else []

        # Per-account breakdown
        billing_by_acct = {}
        billing_by_login = {}
        for entry in billing:
            acct_no = (entry.get("account_no") or "").strip()
            status = (entry.get("status") or "").strip().upper()
            amount = entry.get("paid_amount_numeric", 0.0)
            login_id = str(entry.get("login") or acct_no).strip()
            if acct_no and amount > 0 and status == "APPROVED":
                info = {"amount": amount, "account_no": acct_no, "login": login_id,
                        "date": entry.get("date", ""), "type": entry.get("transition_type", "")}
                if acct_no not in billing_by_acct:
                    billing_by_acct[acct_no] = info
                billing_by_login[login_id] = dict(info)  # last wins

        for login_id, bill_info in billing_by_login.items():
            if login_id in mapping:
                tv = mapping[login_id].get("tradovate_account_name")
                if tv and tv not in billing_by_acct:
                    billing_by_acct[tv] = dict(bill_info)

        print(f"  Per-account fees:")
        for k, v in billing_by_acct.items():
            print(f"    {k}: ${v['amount']:.2f} ({v.get('type', 'N/A')})")

        # Per-firm totals
        total_fees = sum(e.get("paid_amount_numeric", 0.0) for e in billing
                        if (e.get("status") or "").upper() == "APPROVED" and e.get("paid_amount_numeric", 0) > 0)
        total_payouts = 0.0
        for p in payouts:
            for key in ("amount", "payout_amount", "netAmount", "total", "value"):
                val = p.get(key)
                if val is not None:
                    try:
                        total_payouts += abs(float(str(val).replace("$", "").replace(",", "")))
                    except: pass
                    break

        print(f"\n  📊 {name} Summary — Total Fees: ${total_fees:.2f} | Total Payouts: ${total_payouts:.2f}")
        acct.disconnect()
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
