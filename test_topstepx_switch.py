"""
Standalone test for TopStepX account auto-switching.

What it does:
  1. Logs into TopStepX with the credentials passed in (or from env vars).
  2. Reads the list of accounts visible to the user via the API.
  3. For each account, calls switch_account(account_name_contains=<name>) and:
       - measures the time taken
       - reads the MuiSelect text after the call
       - PASS if the dropdown text contains the requested name, FAIL otherwise
  4. Re-runs the same switch a second time to verify the cache fast-path
     (must complete in < 50 ms).

Usage:
  set TSX_USER=you@example.com
  set TSX_PASS=yourpassword
  python test_topstepx_switch.py

  # Or pass on the command line:
  python test_topstepx_switch.py --user you@example.com --password ... [--only "50KTC"]

Exit code 0 if all PASS, 1 otherwise.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Make `trader_companion` importable when run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "trader_companion"))

from selenium.webdriver.common.by import By  # noqa: E402

from topstepx import TopStepXAccount  # noqa: E402


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )


def _read_selector_text(account: TopStepXAccount) -> str:
    try:
        el = account.driver.find_element(
            By.XPATH,
            "//div[contains(@class, 'MuiSelect-select') and contains(@class, 'MuiInputBase-input')]",
        )
        return (el.text or "").strip()
    except Exception as e:
        return f"<read failed: {e}>"


def _list_accounts_via_api(account: TopStepXAccount) -> list[dict]:
    """Pull the visible account list from TopStepX's REST API."""
    try:
        if not getattr(account, "api_available", False):
            return []
        accounts = account.api_get_trading_accounts()
        return accounts if isinstance(accounts, list) else []
    except Exception as e:
        print(f"  [WARN] Could not list accounts via API: {e}")
        return []


def run_test(username: str, password: str, only: str | None = None) -> int:
    print("=" * 70)
    print("TopStepX account auto-switch test")
    print("=" * 70)

    print(f"\n[1/4] Initializing TopStepXAccount for user={username} ...")
    account = TopStepXAccount(username=username, password=password, pair_id="switch_test")

    print("\n[2/4] Logging in (may open Chrome and require existing session) ...")
    if not account.login():
        print("  [FAIL] Login failed — cannot test switching.")
        return 1
    print("  [OK]  Logged in.")

    # Make sure we're on the trade page before reading the selector
    try:
        account._ensure_on_trading_page()
    except Exception as e:
        print(f"  [WARN] _ensure_on_trading_page raised: {e}")

    print("\n[3/4] Discovering available accounts ...")
    api_accounts = _list_accounts_via_api(account)
    if api_accounts:
        names = [a.get("accountName", "") for a in api_accounts if a.get("accountName")]
        print(f"  Found {len(names)} accounts via API:")
        for n in names:
            print(f"    - {n}")
    else:
        # Fall back: open the dropdown and read MuiMenuItem options once
        print("  No accounts via API — falling back to DOM scan of the dropdown.")
        names = []
        try:
            select_el = account.driver.find_element(
                By.XPATH,
                "//div[contains(@class, 'MuiSelect-select') and contains(@class, 'MuiInputBase-input')]",
            )
            account.driver.execute_script("arguments[0].click();", select_el)
            time.sleep(0.6)
            items = account.driver.find_elements(
                By.XPATH, "//li[contains(@class, 'MuiMenuItem-root')] | //*[@role='option']"
            )
            for it in items:
                txt = (it.text or "").strip()
                if txt:
                    names.append(txt)
            # Close dropdown
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(account.driver).send_keys(Keys.ESCAPE).perform()
            print(f"  Found {len(names)} options in dropdown:")
            for n in names:
                print(f"    - {n}")
        except Exception as e:
            print(f"  [FAIL] Could not enumerate accounts via DOM: {e}")
            return 1

    if not names:
        print("  [FAIL] No accounts to test against.")
        return 1

    if only:
        names = [n for n in names if only.lower() in n.lower()]
        if not names:
            print(f"  [FAIL] --only '{only}' filtered out every account.")
            return 1
        print(f"  Filtered to {len(names)} account(s) matching '{only}'.")

    print("\n[4/4] Running switch tests ...")
    total = 0
    passed = 0
    for name in names:
        # Pick a stable substring to switch on. Prefer the trailing account ID
        # (last token after the final '-'), otherwise the full name.
        token = name.split("-")[-1].strip() if "-" in name else name.strip()
        if len(token) < 3:
            token = name

        total += 1
        print(f"\n  Test #{total}: switch to '{token}'  (full name: '{name}')")

        # ── First call (cold) ───────────────────────────────────────────
        # Reset the cache so we measure a real switch each time
        account._last_switched_key = None
        t0 = time.time()
        ok = account.switch_account(account_name_contains=token)
        cold_ms = (time.time() - t0) * 1000
        after_text = _read_selector_text(account)
        cold_pass = bool(ok) and (token.lower() in after_text.lower())
        print(f"    cold call: ok={ok}  {cold_ms:7.1f} ms  selector='{after_text[:80]}'  {'PASS' if cold_pass else 'FAIL'}")

        # ── Second call (warm — should be cache hit) ────────────────────
        t1 = time.time()
        ok2 = account.switch_account(account_name_contains=token)
        warm_ms = (time.time() - t1) * 1000
        warm_pass = bool(ok2) and warm_ms < 50.0
        print(f"    warm call: ok={ok2}  {warm_ms:7.1f} ms  (cache hit expected, < 50 ms)  {'PASS' if warm_pass else 'FAIL'}")

        if cold_pass and warm_pass:
            passed += 1

    print("\n" + "=" * 70)
    print(f"Result: {passed}/{total} accounts passed")
    print("=" * 70)
    return 0 if passed == total else 1


def main():
    _setup_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--user", default=os.environ.get("TSX_USER"))
    p.add_argument("--password", default=os.environ.get("TSX_PASS"))
    p.add_argument("--only", default=None,
                   help="Substring filter — only test accounts containing this text")
    args = p.parse_args()

    if not args.user or not args.password:
        print("Missing credentials.")
        print("  Provide --user/--password on the command line, or set TSX_USER and TSX_PASS env vars.")
        sys.exit(2)

    sys.exit(run_test(args.user, args.password, only=args.only))


if __name__ == "__main__":
    main()
