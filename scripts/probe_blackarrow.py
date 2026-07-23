"""
scripts/probe_blackarrow.py

Attaches to the ALREADY-OPEN BlackArrow Chrome session via remote
debugging (port 9222) and verifies / places a test trade.

Pre-condition
─────────────
The BlackArrow Chrome window must have been started by the trader app's
broker connector (which now includes --remote-debugging-port=9222).
If the browser was started before that flag was added, re-connect the
broker in the app first (it will restart Chrome with the flag).

Usage
─────
# diagnostics only — no order placed
python scripts/probe_blackarrow.py

# place a real 1-contract SELL with no bracket
python scripts/probe_blackarrow.py --side sell --qty 1

# place a BUY with TP=50 ticks, SL=100 ticks
python scripts/probe_blackarrow.py --side buy --qty 1 --tp 50 --sl 100
"""

import argparse
import logging
import sys
import os
import time
import json

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ba_probe")

DEBUG_PORT = 9222


# ── helpers ────────────────────────────────────────────────────────────────

def _ok(msg):   print(f"  \u2705  {msg}")
def _fail(msg): print(f"  \u274c  {msg}")
def _info(msg): print(f"  \u2139   {msg}")
def _sep(title=""):
    print(f"\n{'='*60}")
    if title: print(f"  {title}")
    print(f"{'='*60}")


def attach_to_chrome(port: int = DEBUG_PORT):
    """
    Attach Selenium to the already-open Chrome on the given debug port.
    Returns a webdriver.Chrome instance or raises.
    """
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"localhost:{port}")
    # Don't pass a chromedriver binary — use whatever's on PATH / managed by Selenium Manager
    try:
        driver = webdriver.Chrome(options=opts)
        _ok(f"Attached to Chrome on port {port}  (title: {driver.title!r})")
        return driver
    except Exception as e:
        raise RuntimeError(
            f"Could not attach to Chrome on port {port}.\n"
            f"  Make sure the broker connector started Chrome (reconnect if needed).\n"
            f"  Error: {e}"
        )


# ── diagnostic steps ───────────────────────────────────────────────────────

def step_page_info(driver):
    _sep("1 — Page info")
    _info(f"URL  : {driver.current_url}")
    _info(f"Title: {driver.title}")
    if "blackarrow" not in driver.current_url.lower():
        _fail("Not on blackarrowtrading.com — wrong tab or not connected")
        return False
    _ok("On BlackArrow platform")
    return True


def step_dom_snapshot(driver):
    _sep("2 — DOM snapshot (buttons / checkboxes / inputs)")

    result = driver.execute_script("""
        var out = { buttons: [], checkboxes: [], inputs: [] };

        // All visible buttons with text
        Array.from(document.querySelectorAll('button, ion-button')).forEach(function(b) {
            if (b.offsetParent === null) return;
            var r = b.getBoundingClientRect();
            if (r.width < 5) return;
            out.buttons.push({
                text: b.textContent.trim().substring(0, 40),
                w: Math.round(r.width), h: Math.round(r.height),
                x: Math.round(r.x), y: Math.round(r.y)
            });
        });

        // Checkboxes
        Array.from(document.querySelectorAll('input[type="checkbox"]')).forEach(function(c) {
            if (c.offsetParent === null) return;
            // Find nearest label
            var lbl = document.querySelector('label[for="' + c.id + '"]');
            var t = lbl ? lbl.textContent.trim() : (c.name || c.id || '?');
            out.checkboxes.push({ label: t, checked: c.checked });
        });

        // Visible number inputs
        Array.from(document.querySelectorAll('input[type="number"], input[type="text"]'))
            .filter(function(i) {
                var r = i.getBoundingClientRect();
                return r.width > 20 && r.height > 8;
            }).forEach(function(i) {
                out.inputs.push({
                    placeholder: i.placeholder,
                    value: i.value,
                    class: (i.className || '').substring(0, 40)
                });
            });

        return out;
    """)

    _info("Buttons:")
    for b in result.get("buttons", []):
        print(f"       [{b['w']:3d}x{b['h']:2d} @ ({b['x']:4d},{b['y']:4d})]  {b['text']!r}")

    _info("Checkboxes:")
    for c in result.get("checkboxes", []):
        print(f"       checked={c['checked']}  label={c['label']!r}")

    _info("Inputs:")
    for i in result.get("inputs", []):
        print(f"       value={i['value']!r}  placeholder={i['placeholder']!r}  class={i['class']!r}")

    return result


def step_order_panel_check(driver):
    _sep("3 — Order panel buttons detection")
    result = driver.execute_script("""
        var wanted = ['Buy at Mkt', 'Sell at Mkt', 'Sell', 'B Stop', 'Close', 'Cancel Orders + Close'];
        var found = {};
        var all = Array.from(document.querySelectorAll('button, ion-button'));
        for (var w of wanted) {
            var match = all.find(function(b) {
                return b.offsetParent !== null && b.textContent.trim() === w;
            });
            found[w] = !!match;
        }
        return found;
    """)
    all_ok = True
    for btn, present in result.items():
        if present:
            _ok(f"Button found: {btn!r}")
        else:
            _fail(f"Button MISSING: {btn!r}")
            if btn in ('Buy at Mkt', 'Sell at Mkt'):
                all_ok = False
    return all_ok


def step_account_stats(driver):
    _sep("4 — Account stats scrape")
    stats = {}

    try:
        bal = driver.execute_script("""
            const els = document.querySelectorAll('nav *');
            for (const el of els) {
                if (el.children.length === 0) {
                    const t = el.textContent.trim();
                    if (/^\\$ [\\d,]+\\.\\d{2}$/.test(t)) return t;
                }
            }
            return null;
        """)
        if bal:
            stats["Balance"] = bal
    except Exception as e:
        _info(f"Balance scrape error: {e}")

    for label, key in (
        ("MLL", "MLL"), ("Max Loss", "MLL"), ("DD Limit", "MLL"),
        ("SOD Balance", "SOD Balance"), ("Daily PnL", "DailyPnL"),
    ):
        if key in stats:
            continue
        try:
            val = driver.execute_script("""
                (function(lbl) {
                    const infos = document.querySelectorAll('.info');
                    for (const info of infos) {
                        const k = info.querySelector('span.key');
                        const v = info.querySelector('span.value');
                        if (k && v && k.textContent.trim() === lbl) return v.textContent.trim();
                    }
                    return null;
                })(arguments[0]);
            """, label)
            if val:
                stats[key] = val
        except Exception:
            pass

    if stats:
        for k, v in stats.items():
            _ok(f"{k}: {v}")
    else:
        _fail("No stats found — stats panel may not be visible on screen")

    return stats


def step_position_panel(driver):
    _sep("4b — Position panel raw text (Avg / PnL / Balance rows)")
    result = driver.execute_script(r"""
        // Collect all leaf text nodes that look like labels or prices
        var rows = [];
        var all = Array.from(document.querySelectorAll('*'));
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.children.length > 0) continue;
            var t = el.textContent.trim();
            if (!t || t.length > 60) continue;
            // Keep labels and dollar amounts
            if (/avg|balance|pnl|total|open|daily|margin/i.test(t) ||
                /^\$[\s\d,\.]+$/.test(t) ||
                /^\-?\d[\d,\.]*$/.test(t)) {
                var r = el.getBoundingClientRect();
                rows.push({ text: t, x: Math.round(r.x), y: Math.round(r.y) });
            }
        }
        // Sort by y (top to bottom) then x (left to right)
        rows.sort(function(a, b) { return a.y - b.y || a.x - b.x; });
        return rows;
    """)
    _info("Position panel leaf nodes (label/price text):")
    for row in result:
        print(f"       ({row['x']:5d},{row['y']:4d})  {row['text']!r}")
    return result


    _sep(f"5 — Place order  {side.upper()} qty={qty} TP={tp or 'none'} SL={sl or 'none'}")

    # Import and use the connector helpers by temporarily wiring driver into one
    from connectors.blackarrow_connector import BlackArrowConnector
    conn = BlackArrowConnector.__new__(BlackArrowConnector)
    conn._driver    = driver
    conn._connected = True
    conn.email      = "probe"
    conn.password   = ""
    conn.account_id = ""
    conn.headless   = False

    print()
    if not auto:
        confirm = input(
            f"  ⚠  This places a REAL {side.upper()} {qty} contract order. Type 'yes' to proceed: "
        ).strip().lower()
        if confirm != "yes":
            _info("Skipped by user.")
            return None
    else:
        _info(f"--auto: skipping confirmation, placing {side.upper()} {qty} now...")

    try:
        ok = conn.place_order(
            symbol="NQFUT",
            side=side,
            qty=qty,
            tp_ticks=tp if tp > 0 else None,
            sl_ticks=sl if sl > 0 else None,
        )
        if ok:
            _ok(f"place_order() returned True — order submitted!")
        else:
            _fail(f"place_order() returned {ok!r}")
        return ok
    except Exception as e:
        _fail(f"place_order() raised: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        return False


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BlackArrow Chrome probe")
    parser.add_argument("--port",  type=int, default=DEBUG_PORT, help=f"Chrome debug port (default {DEBUG_PORT})")
    parser.add_argument("--side",  default="",    help="buy or sell  (omit to skip order)")
    parser.add_argument("--qty",   type=int, default=1, help="Contract qty (default 1)")
    parser.add_argument("--tp",    type=int, default=0, help="TP ticks, 0=none")
    parser.add_argument("--sl",    type=int, default=0, help="SL ticks, 0=none")
    parser.add_argument("--auto",  action="store_true", help="Skip 'yes' confirmation prompt")
    args = parser.parse_args()

    _sep("BlackArrow Chrome Probe")

    # Attach to running Chrome
    try:
        driver = attach_to_chrome(args.port)
    except RuntimeError as e:
        print(f"\n{e}\n")
        sys.exit(1)

    # Run diagnostics
    step_page_info(driver)
    snapshot = step_dom_snapshot(driver)
    panel_ok = step_order_panel_check(driver)
    stats = step_account_stats(driver)
    pos_rows = step_position_panel(driver)

    # Place order if requested
    if args.side:
        if args.side.lower() not in ("buy", "sell"):
            print(f"\nInvalid --side '{args.side}'. Use 'buy' or 'sell'.")
            sys.exit(1)
        step_place_order(driver, args.side, args.qty, args.tp, args.sl, auto=args.auto)

    _sep("Probe complete — browser left open")


if __name__ == "__main__":
    main()
