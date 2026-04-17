"""Test FundedNextAccount.get_account_stats() against live Chrome"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"C:\Users\harry\Music\MT5HedgingEngine")

from trader_companion.fundednext import FundedNextAccount

# Connect to existing Chrome on port 9549
fn = FundedNextAccount(attach_to_existing=True, debug_port=9549)

print(f"Connected: {fn.is_connected()}")
print(f"URL: {fn.driver.current_url}")

# Switch to Futures > Active (where the account is)
fn.switch_type_tab("Futures")
fn.switch_status_tab("Active")

print(f"\nHas accounts: {fn.has_accounts()}")

print("\n=== get_account_stats() ===")
stats = fn.get_account_stats()
for k, v in stats.items():
    print(f"  {k}: {v}")

print("\n=== get_all_accounts() ===")
all_accts = fn.get_all_accounts()
print(f"Total accounts found: {len(all_accts)}")
for i, acct in enumerate(all_accts):
    print(f"\n--- Account {i+1} ---")
    for k, v in acct.items():
        print(f"  {k}: {v}")

print("\nDone!")
