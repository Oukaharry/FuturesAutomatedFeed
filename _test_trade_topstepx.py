"""
Test trade placement on TopStepX
BUY 1x MNQM26 with TP=$100, SL=$200
Verifies the order form entries and post-trade TP/SL setup
"""
import sys, os, time, logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

sys.path.insert(0, os.path.dirname(__file__))
from trader_companion.topstepx import TopStepXAccount

USERNAME = "livemoreabundantlyllc@gmail.com"
PASSWORD = "FTn4t4fx6Mna"

SYMBOL = "MNQM26"
QUANTITY = 1
TP_DOLLARS = 100
SL_DOLLARS = 200
SIDE = "BUY"

def main():
    print("=" * 70)
    print(f"  TEST TRADE: {SIDE} {QUANTITY}x {SYMBOL}  |  TP=${TP_DOLLARS}  SL=${SL_DOLLARS}")
    print("=" * 70)

    acct = TopStepXAccount(username=USERNAME, password=PASSWORD)

    # --- LOGIN ---
    print("\n[1] Logging in...")
    if not acct.login():
        print("LOGIN FAILED - aborting")
        return
    print("   Logged in OK")
    time.sleep(2)

    # --- CHECK ACCOUNT STATUS VIA API ---
    if acct.api_available:
        print("\n[2] Checking account status via API...")
        accounts = acct.api_get_trading_accounts()
        if accounts and isinstance(accounts, list):
            for a in accounts:
                name = a.get("accountName", "?")
                bal = a.get("balance", 0)
                status = a.get("status", "?")
                inelig = a.get("ineligible", "?")
                print(f"   {name}  balance=${bal:.2f}  status={status}  ineligible={inelig}")
                if inelig:
                    print("   *** ACCOUNT IS INELIGIBLE - trade may be rejected ***")

        # Check positions before trade
        positions = acct.api_get_positions()
        print(f"\n[3] Existing positions: {positions if positions else 'none'}")

        # Check open orders before trade  
        orders = acct.api_get_orders()
        print(f"   Existing orders: {orders if orders else 'none'}")
    else:
        print("\n[2] API not available, skipping pre-trade checks")

    # --- NAVIGATE TO TRADING PAGE ---
    print("\n[4] Ensuring on trading page...")
    acct._ensure_on_trading_page()
    time.sleep(1)

    # --- SCREENSHOT BEFORE ---
    try:
        acct.driver.save_screenshot("_test_trade_BEFORE.png")
        print("   Screenshot saved: _test_trade_BEFORE.png")
    except:
        pass

    # --- PLACE THE TRADE ---
    print(f"\n[5] PLACING ORDER: {SIDE} {QUANTITY}x {SYMBOL} | TP=${TP_DOLLARS} SL=${SL_DOLLARS}")
    print("   This will:")
    print("   a) Switch to Order tab")
    print("   b) Set symbol to MNQM26")
    print("   c) Set quantity to 1")
    print("   d) Attempt to set TP/SL on order form")
    print("   e) Click BUY button")
    print("   f) Switch to Positions tab and edit TP/SL inline")
    print()

    start = time.time()
    result = acct.place_buy_order(
        symbol=SYMBOL,
        quantity=QUANTITY,
        order_type="market",
        tp_dollars=TP_DOLLARS,
        sl_dollars=SL_DOLLARS,
        skip_post_trade_setup=False  # Do full TP/SL setup
    )
    elapsed = time.time() - start

    print(f"\n{'=' * 70}")
    print(f"  ORDER RESULT  ({elapsed:.1f}s)")
    print(f"{'=' * 70}")
    for k, v in result.items():
        print(f"   {k}: {v}")

    # --- SCREENSHOT AFTER ---
    try:
        acct.driver.save_screenshot("_test_trade_AFTER.png")
        print("\n   Screenshot saved: _test_trade_AFTER.png")
    except:
        pass

    # --- VERIFY VIA API ---
    if acct.api_available:
        time.sleep(2)
        print("\n[6] Post-trade verification via API...")

        positions = acct.api_get_positions()
        print(f"   Positions: {positions if positions else 'none'}")

        orders = acct.api_get_orders()
        print(f"   Orders: {orders if orders else 'none'}")

        linked = acct.api_get_linked_orders()
        print(f"   Linked/Bracket orders: {linked}")

    # --- VERIFY VIA DOM ---
    print("\n[7] Checking positions tab for TP/SL values...")
    try:
        acct.switch_to_positions_tab()
        time.sleep(1.5)

        # Read the positions grid to verify TP/SL were set
        grid_text = acct.driver.execute_script("""
            const rows = document.querySelectorAll('[role="row"]');
            let result = [];
            rows.forEach(r => {
                const cells = r.querySelectorAll('[role="gridcell"], [role="columnheader"]');
                if (cells.length > 0) {
                    let rowData = Array.from(cells).map(c => c.textContent.trim());
                    result.push(rowData.join(' | '));
                }
            });
            return result;
        """)
        if grid_text:
            print("   Positions grid content:")
            for row in grid_text[:10]:  # First 10 rows max
                print(f"     {row}")
        else:
            print("   No grid rows found")
    except Exception as e:
        print(f"   Grid check failed: {e}")

    # --- FINAL SCREENSHOT ---
    try:
        acct.driver.save_screenshot("_test_trade_FINAL.png")
        print("\n   Screenshot saved: _test_trade_FINAL.png")
    except:
        pass

    print(f"\n{'=' * 70}")
    print("  TEST COMPLETE")
    print(f"{'=' * 70}")
    input("\nPress Enter to close Chrome and exit...")
    acct.disconnect()

if __name__ == "__main__":
    main()
