"""Verify FundedNext billing entries are correctly separated per account."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import FundedNextCDPAccount

acct = FundedNextCDPAccount(debug_port=9222)
acct.login()

# Get mapping first (need to be on accounts page)
acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
time.sleep(5)
acct._switch_type_tab("Futures")
time.sleep(3)
mapping = acct.get_account_mapping()

# Get billing
acct._js("window.location.href = 'https://app.fundednext.com/billing/billing-history'")
time.sleep(5)
billing = acct.get_billing_history()

print(f"=== Account Mapping ({len(mapping)}) ===")
for k, v in mapping.items():
    print(f"  {k} -> {v.get('tradovate_account_name')}")

print(f"\n=== Billing Records ({len(billing)}) ===")
for b in billing:
    print(f"  acct={b['account_no']} | login={b.get('login')} | "
          f"{b['paid_amount']} | {b.get('transition_type', 'N/A')} | {b['date']}")

# Simulate the _autofill_challenge_fees logic (first-wins / last-wins)
billing_by_acct = {}
billing_by_login = {}
for entry in billing:
    acct_no = (entry.get("account_no") or "").strip()
    status = (entry.get("status") or "").strip().upper()
    amount = entry.get("paid_amount_numeric", 0.0)
    login_id = str(entry.get("login") or acct_no).strip()
    if acct_no and amount > 0 and status == "APPROVED":
        info = {"amount": amount, "account_no": acct_no, "login": login_id,
                "date": entry.get("date", ""), "package": entry.get("funding_package", "")}
        # First entry wins for billing_by_acct
        if acct_no not in billing_by_acct:
            billing_by_acct[acct_no] = info
        # Last entry wins for billing_by_login
        billing_by_login[login_id] = dict(info)

# Resolve login -> Tradovate
for login_id, bill_info in billing_by_login.items():
    if login_id in mapping:
        tv_name = mapping[login_id].get("tradovate_account_name")
        if tv_name and tv_name not in billing_by_acct:
            enriched = dict(bill_info)
            enriched["tradovate_account_name"] = tv_name
            billing_by_acct[tv_name] = enriched

print(f"\n=== billing_by_acct (should have 2 separate entries) ===")
for key, info in billing_by_acct.items():
    print(f"  {key}: ${info['amount']:.2f} | {info.get('date')}")

print(f"\n=== EXPECTED ===")
print(f"  946645337: $139.04 (original purchase, old breached account)")
print(f"  FNFTCHHARRISONOUKA22342: $142.13 (reset fee, current active account)")

acct.disconnect()
