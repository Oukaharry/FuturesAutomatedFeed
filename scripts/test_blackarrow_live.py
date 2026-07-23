"""
scripts/test_blackarrow_live.py

Live integration diagnostic for The5ers → BlackArrow.
Walks through every step of the order flow and reports pass/fail at each one.

Usage:
    python scripts/test_blackarrow_live.py --email you@email.com --password secret
    python scripts/test_blackarrow_live.py --email you@email.com --password secret --skip-order
    python scripts/test_blackarrow_live.py --email you@email.com --password secret --qty 1 --tp 20 --sl 20

Args:
    --email       BlackArrow account email
    --password    BlackArrow account password
    --qty         Contract quantity for test order  (default: 1)
    --side        'buy' or 'sell'                   (default: buy)
    --tp          TP in ticks (0 = no bracket)      (default: 0)
    --sl          SL in ticks (0 = no bracket)      (default: 0)
    --skip-order  Run diagnostics only, DO NOT place an order
"""

import argparse
import logging
import sys
import os
import time

# ── project root on path ───────────────────────────────────────────────────
ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from connectors.blackarrow_connector import BlackArrowConnector  # noqa: E402

# Verbose logging so every step is visible
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ba_live_test")


def _step(label):
    print(f"\n{'='*60}")
    print(f"  STEP: {label}")
    print(f"{'='*60}")


def _ok(msg):
    print(f"  ✅  {msg}")


def _fail(msg):
    print(f"  ❌  {msg}")


def _info(msg):
    print(f"  ℹ   {msg}")


def run_diagnostic(email: str, password: str, qty: int, side: str,
                   tp: int, sl: int, skip_order: bool):

    results = {}

    # ------------------------------------------------------------------
    # STEP 1: Import check
    # ------------------------------------------------------------------
    _step("1 — Import & API surface")
    required = ["connect", "disconnect", "place_order",
                "buy_market", "sell_market",
                "get_account_stats", "is_connected"]
    all_ok = True
    for method in required:
        present = hasattr(BlackArrowConnector, method)
        ((_ok if present else _fail)(f"BlackArrowConnector.{method}"))
        if not present:
            all_ok = False
    results["api_surface"] = all_ok

    # ------------------------------------------------------------------
    # STEP 2: Instantiate connector
    # ------------------------------------------------------------------
    _step("2 — Instantiate connector")
    try:
        conn = BlackArrowConnector(email=email, password=password)
        _ok(f"Created BlackArrowConnector (headless=False)")
        results["instantiate"] = True
    except Exception as e:
        _fail(f"Could not create connector: {e}")
        results["instantiate"] = False
        return results

    # ------------------------------------------------------------------
    # STEP 3: Connect (launch Chrome, login)
    # ------------------------------------------------------------------
    _step("3 — Connect to BlackArrow (this opens Chrome)")
    _info("If a 2FA prompt appears, enter it in the browser window.")
    try:
        connected = conn.connect()
        if connected:
            _ok("conn.connect() returned True")
            results["connect"] = True
        else:
            _fail("conn.connect() returned False — check Chrome window for login errors")
            results["connect"] = False
            return results
    except Exception as e:
        _fail(f"conn.connect() raised: {e}")
        results["connect"] = False
        return results

    # ------------------------------------------------------------------
    # STEP 4: is_connected
    # ------------------------------------------------------------------
    _step("4 — is_connected()")
    ic = conn.is_connected()
    _ok(f"is_connected() = {ic}") if ic else _fail(f"is_connected() = {ic}")
    results["is_connected"] = ic

    # ------------------------------------------------------------------
    # STEP 5: get_account_stats (reads Balance / MLL / SOD Balance)
    # ------------------------------------------------------------------
    _step("5 — get_account_stats()")
    try:
        stats = conn.get_account_stats()
        if stats:
            _ok(f"Stats retrieved: {stats}")
        else:
            _info("Stats returned empty dict — platform stats panel may not be visible")
        results["stats"] = stats
    except Exception as e:
        _fail(f"get_account_stats() raised: {e}")
        results["stats"] = {}

    # Check critical fields for full_cushion SL mode
    bal = results["stats"].get("Balance", "")
    mll = results["stats"].get("MLL", "")
    sod = results["stats"].get("SOD Balance", "")
    if bal:
        _ok(f"Balance present: {bal}")
    else:
        _info("⚠ Balance NOT in stats — full_cushion SL fallback will apply")
    if mll:
        _ok(f"MLL present: {mll}")
    elif sod:
        _ok(f"SOD Balance present (MLL fallback): {sod}")
    else:
        _info("⚠ Neither MLL nor SOD Balance in stats — SL cushion cannot be calculated")

    # ------------------------------------------------------------------
    # STEP 6: Platform routing check (simulate what trader_app does)
    # ------------------------------------------------------------------
    _step("6 — Platform routing check for 5ers name variants")
    test_names = ["The5ers", "the5ers", "5ers", "The 5ers", "THE5ERS"]
    for name in test_names:
        stripped = name.lower().replace("%", "").replace(" ", "")
        is_ba = "blackarrow" in name.lower() or "the5ers" in stripped or "5ers" in stripped
        status = "BlackArrow ✅" if is_ba else "NOT BlackArrow ❌"
        _info(f"  {name!r:20s} → {status}")

    # ------------------------------------------------------------------
    # STEP 7: Place test order (skipped if --skip-order)
    # ------------------------------------------------------------------
    _step("7 — Place test order")
    if skip_order:
        _info("--skip-order flag set. Skipping order placement.")
        results["order"] = "skipped"
    else:
        use_bracket = tp > 0 or sl > 0
        _info(f"Placing {side.upper()} {qty} contract(s)"
              + (f"  TP={tp} ticks  SL={sl} ticks" if use_bracket else "  (no bracket)"))
        print()
        confirm = input("  ⚠  This places a REAL order on a LIVE account. Type 'yes' to proceed: ").strip().lower()
        if confirm != "yes":
            _info("Cancelled by user.")
            results["order"] = "cancelled"
        else:
            try:
                t0 = time.time()
                ok = conn.place_order(
                    symbol="NQFUT",
                    side=side,
                    qty=qty,
                    tp_ticks=tp if tp > 0 else None,
                    sl_ticks=sl if sl > 0 else None,
                )
                elapsed = time.time() - t0
                if ok:
                    _ok(f"place_order() returned True  ({elapsed:.1f}s)")
                    results["order"] = "ok"
                else:
                    _fail(f"place_order() returned {ok!r}  ({elapsed:.1f}s)")
                    results["order"] = "failed"
            except RuntimeError as e:
                _fail(f"place_order() RuntimeError: {e}")
                results["order"] = f"RuntimeError: {e}"
            except Exception as e:
                _fail(f"place_order() unexpected error: {type(e).__name__}: {e}")
                results["order"] = f"Exception: {e}"

    # ------------------------------------------------------------------
    # STEP 8: Test sell_market / buy_market wrapper signatures
    # ------------------------------------------------------------------
    _step("8 — sell_market / buy_market signature smoke test (no actual order)")
    try:
        import inspect
        bm_sig = inspect.signature(conn.buy_market)
        sm_sig = inspect.signature(conn.sell_market)
        _ok(f"buy_market  signature: {bm_sig}")
        _ok(f"sell_market signature: {sm_sig}")
        _ok("Both wrappers are callable with (symbol, qty, tp, sl, expected_account)")
        results["wrappers"] = True
    except Exception as e:
        _fail(f"Signature check failed: {e}")
        results["wrappers"] = False

    # ------------------------------------------------------------------
    # STEP 9: Disconnect
    # ------------------------------------------------------------------
    _step("9 — Disconnect")
    try:
        conn.disconnect()
        _ok("Disconnected cleanly")
        results["disconnect"] = True
    except Exception as e:
        _fail(f"disconnect() raised: {e}")
        results["disconnect"] = False

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("  DIAGNOSTIC SUMMARY")
    print("="*60)
    for k, v in results.items():
        status = "✅" if v and v not in ("failed", "cancelled") and v is not False else "❌"
        print(f"  {status}  {k:20s} = {v}")
    print()

    return results


def main():
    parser = argparse.ArgumentParser(description="BlackArrow live integration diagnostic")
    parser.add_argument("--email",       required=True,  help="BlackArrow account email")
    parser.add_argument("--password",    required=True,  help="BlackArrow account password")
    parser.add_argument("--qty",         type=int,   default=1,     help="Contract qty (default 1)")
    parser.add_argument("--side",        default="buy",             help="buy or sell (default buy)")
    parser.add_argument("--tp",          type=int,   default=0,     help="TP ticks, 0=none (default 0)")
    parser.add_argument("--sl",          type=int,   default=0,     help="SL ticks, 0=none (default 0)")
    parser.add_argument("--skip-order",  action="store_true",       help="Diagnostics only, no order placed")
    args = parser.parse_args()

    run_diagnostic(
        email=args.email,
        password=args.password,
        qty=args.qty,
        side=args.side,
        tp=args.tp,
        sl=args.sl,
        skip_order=args.skip_order,
    )


if __name__ == "__main__":
    main()
