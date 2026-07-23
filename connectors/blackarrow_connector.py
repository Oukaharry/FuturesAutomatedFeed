"""
blackarrow_connector.py — Selenium-based connector for BlackArrow (Nelogica) trading platform.

Platform: https://web.blackarrowtrading.com/
Uses Selenium (system Chrome, same anti-detection approach as TradovateAccount).
No Playwright — no "Test" / "Chrome is controlled by automation" banner.

Login form selectors (live-verified):
  Email:    input[type="email"]  or  input[placeholder*="mail" i]
  Password: input[type="password"]
  Submit:   button[type="submit"]  or  button text "Enter"

Stats DOM (Nelogica/Hades UI):
  Balance: leaf <nav *> node matching /^\\$ [\\d,]+\\.\\d{2}$/
  Stats:   .info > span.key (label) + span.value (value)

USAGE:
    conn = BlackArrowConnector(email="u@example.com", password="secret")
    conn.connect()
    conn.place_order("NQFUT", side="buy", qty=1, tp_ticks=50, sl_ticks=100)
    conn.close_all()
    conn.disconnect()
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

BLACKARROW_URL   = "https://web.blackarrowtrading.com/"
DEFAULT_WAIT     = 30     # seconds
CONFIRM_WAIT     = 3      # seconds for confirmation dialogs (short — dialog is optional)
ORDER_SETTLE     = 2.0    # seconds after placing an order
DEBUG_PORT       = 9222   # Chrome remote-debugging port (probe / diagnostics)
FILL_WAIT        = 5      # seconds to poll for Avg fill price after market entry

# Tick sizes (minimum price increment) for supported instruments.
# BlackArrow uses price-based TP/SL orders, so ticks → price offset.
TICK_SIZES: dict = {
    "NQFUT":  0.25,
    "NQU6":   0.25,
    "NQFU6":  0.25,
    "MNQFUT": 0.25,
    "MNQU6":  0.25,
}


class BlackArrowConnector:
    """
    Selenium-based connector for web.blackarrowtrading.com.

    Uses system Chrome with anti-detection flags (same as TradovateAccount)
    so no automation banner appears and persistent login is preserved.

    Parameters
    ----------
    email : str
        BlackArrow account email.
    password : str
        BlackArrow account password.
    account_id : str
        Numeric account ID shown on the platform (e.g. '2947168'). Optional.
    headless : bool
        Run Chrome headless. Default False (2FA needs a visible window).
    """

    def __init__(
        self,
        email:      str,
        password:   str,
        account_id: str  = "",
        headless:   bool = False,
    ):
        self.email      = email
        self.password   = password
        self.account_id = account_id
        self.headless   = headless

        self._driver:    Optional[webdriver.Chrome] = None
        self._connected: bool = False

    # ================================================================== #
    # Public API
    # ================================================================== #

    # ------------------------------------------------------------------ #
    # Shadow-DOM helpers (BlackArrow is a Capacitor/Ionic app — inputs live
    # inside ion-input shadow roots, not as regular <input> elements)
    # ------------------------------------------------------------------ #

    def _fill_ionic_input(self, nth: int, value: str) -> bool:
        """
        Fill the nth ion-input on the page by piercing its shadow DOM.
        Returns True on success.
        """
        return bool(self._driver.execute_script("""
            var ionInputs = document.querySelectorAll('ion-input');
            var el = ionInputs[arguments[0]];
            if (!el) return false;
            // Try shadow root first (Ionic renders <input> inside shadow DOM)
            var inp = el.shadowRoot ? el.shadowRoot.querySelector('input') : el.querySelector('input');
            if (!inp) return false;
            inp.focus();
            var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(inp, arguments[1]);
            inp.dispatchEvent(new Event('ionInput',  { bubbles: true }));
            inp.dispatchEvent(new Event('input',     { bubbles: true }));
            inp.dispatchEvent(new Event('change',    { bubbles: true }));
            inp.dispatchEvent(new Event('ionChange', { bubbles: true }));
            return true;
        """, nth, value))

    def _click_ionic_button(self, text: str) -> bool:
        """Click an ion-button or regular button whose visible text matches."""
        return bool(self._driver.execute_script("""
            var text = arguments[0].toLowerCase().trim();
            // ion-button
            var ionBtns = document.querySelectorAll('ion-button');
            for (var b of ionBtns) {
                if (b.textContent.trim().toLowerCase() === text) { b.click(); return true; }
            }
            // regular button
            var btns = document.querySelectorAll('button');
            for (var b of btns) {
                if (b.textContent.trim().toLowerCase() === text) { b.click(); return true; }
            }
            // partial match fallback
            for (var b of ionBtns) {
                if (b.textContent.toLowerCase().includes(text)) { b.click(); return true; }
            }
            return false;
        """, text))

    def connect(self) -> bool:
        """Launch Chrome, navigate to BlackArrow, auto-login. Returns True on success."""
        try:
            self._driver = self._init_driver()
        except Exception as e:
            logger.error("BlackArrow: Chrome launch failed: %s", e)
            return False

        self._driver.get(BLACKARROW_URL)
        wait = WebDriverWait(self._driver, DEFAULT_WAIT)

        try:
            # Wait for login form or already-logged-in platform
            wait.until(lambda d: self._has_login_form(d) or self._platform_ready(d))

            if self._has_login_form(self._driver):
                logger.info("BlackArrow: filling login form (Ionic/Capacitor shadow DOM)...")

                # BlackArrow uses ion-input components — inputs are inside shadow roots.
                # ion-input[0] = Email, ion-input[1] = Password
                for attempt in range(3):
                    ok_email = self._fill_ionic_input(0, self.email)
                    ok_pass  = self._fill_ionic_input(1, self.password)
                    if ok_email and ok_pass:
                        break
                    time.sleep(1)

                if not ok_email or not ok_pass:
                    logger.warning("BlackArrow: ion-input fill failed, trying direct input selectors...")
                    # Fallback: standard input selectors
                    try:
                        fields = self._driver.find_elements(By.CSS_SELECTOR, 'input')
                        if len(fields) >= 2:
                            fields[0].clear(); fields[0].send_keys(self.email)
                            fields[1].clear(); fields[1].send_keys(self.password)
                    except Exception as fe:
                        logger.warning("BlackArrow: fallback input fill failed: %s", fe)

                time.sleep(0.5)

                # Click Enter / submit button
                clicked = self._click_ionic_button("enter")
                if not clicked:
                    clicked = self._click_ionic_button("login")
                if not clicked:
                    # Last resort: find any submit button
                    try:
                        sub = self._driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], ion-button')
                        sub.click()
                        clicked = True
                    except Exception:
                        pass
                logger.info("BlackArrow: login submitted (clicked=%s).", clicked)

                # Check for 2FA
                try:
                    WebDriverWait(self._driver, 10).until(lambda d:
                        d.find_elements(By.CSS_SELECTOR,
                            'input[placeholder*="code" i], input[maxlength="6"], [class*="otp" i], [class*="2fa" i]')
                        or d.find_elements(By.TAG_NAME, 'ion-input') and
                           len(d.find_elements(By.TAG_NAME, 'ion-input')) == 1
                    )
                    logger.warning(
                        "BlackArrow: 2FA required — please enter the 6-digit code "
                        "in the Chrome window that opened. Waiting up to 120 s..."
                    )
                    print("\n>>> BlackArrow 2FA: check your email and enter the code in the browser window. <<<\n")
                    # Wait for 2FA form to disappear (user submitted)
                    WebDriverWait(self._driver, 120).until(lambda d: self._platform_ready(d))
                except Exception:
                    logger.debug("No 2FA dialog detected — proceeding.")

            # Wait for platform to fully load (canvas / chart area)
            wait.until(lambda d: self._platform_ready(d))
            self._connected = True
            # Auto-detect account ID from the nav bar if not supplied
            if not self.account_id:
                detected = self._read_account_id()
                if detected:
                    self.account_id = detected
                    logger.info("BlackArrow: detected account_id=%s", detected)
            logger.info("BlackArrow: platform ready.")

        except Exception as e:
            logger.error("BlackArrow: login/platform load failed: %s", e)
            self._connected = False

        return self._connected

    def disconnect(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
        self._connected = False
        logger.info("BlackArrow: disconnected.")

    def place_order(
        self,
        symbol:   str,
        side:     str,
        qty:      int            = 1,
        tp_ticks: Optional[int] = None,
        sl_ticks: Optional[int] = None,
    ) -> bool:
        """
        Place a market order then attach TP/SL as separate limit/stop orders.

        UI flow (persistent order panel — no popup ticket):
          1. Set Qty in the panel's Qty field.
          2. Click 'Buy at Mkt' or 'Sell at Mkt' for the market entry.
          3. Confirm any dialog.
          4. Wait for the Avg fill price to appear in the position panel.
          5. For TP: set Price → click 'Sell' (long) or 'B Stop' (short).
          6. For SL: set Price → click 'Sell' (long) or 'B Stop' (short).

        The platform auto-detects limit vs stop based on whether the price is
        above or below the current market — same pattern as Tradovate OCO legs.
        """
        if not self._driver or not self._connected:
            raise RuntimeError(
                "BlackArrow not connected — open the broker panel and click Connect first"
            )

        side_lower = side.lower()
        logger.info(
            "BlackArrow: placing %s %s qty=%d tp=%s sl=%s",
            side_lower, symbol, qty, tp_ticks, sl_ticks,
        )

        # ── 1. Set quantity ──────────────────────────────────────────────
        self._set_qty_field(qty)
        time.sleep(0.2)

        # ── 2. Market entry ──────────────────────────────────────────────
        entry_btn = "Buy at Mkt" if side_lower == "buy" else "Sell at Mkt"
        if not self._click_ionic_button(entry_btn):
            raise RuntimeError(
                f"BlackArrow: could not find '{entry_btn}' button — "
                "is the Order panel visible?"
            )
        self._confirm_order_dialog()
        time.sleep(ORDER_SETTLE)

        # ── 3. Nothing more to do if no TP / SL requested ───────────────
        if not tp_ticks and not sl_ticks:
            logger.info("BlackArrow: market order complete (no TP/SL).")
            return True

        # ── 4. Read fill price from position panel ───────────────────────
        avg_price: Optional[float] = None
        for _ in range(FILL_WAIT):
            avg_price = self._get_avg_price()
            if avg_price:
                break
            time.sleep(1.0)

        if not avg_price:
            logger.warning(
                "BlackArrow: could not read Avg fill price after %ds — "
                "TP/SL orders skipped",
                FILL_WAIT,
            )
            return True

        tick     = TICK_SIZES.get(symbol.upper(), 0.25)
        # Snap avg price to the nearest valid tick — eliminates any DOM-parsing float noise
        avg_snapped = self._snap_to_tick(avg_price, tick)
        if avg_snapped != avg_price:
            logger.debug(
                "BlackArrow: avg_price %.4f snapped to %.2f (tick=%.2f)",
                avg_price, avg_snapped, tick,
            )
        avg_price = avg_snapped

        # For long:  exit via 'Sell' (limit above, stop below)
        # For short: exit via 'B Stop' (limit below, stop above)
        exit_btn = "Sell" if side_lower == "buy" else "B Stop"

        # ── 5. Place TP order ────────────────────────────────────────────
        if tp_ticks:
            tp_price = self._snap_to_tick(
                avg_price + tp_ticks * tick if side_lower == "buy"
                else avg_price - tp_ticks * tick,
                tick,
            )
            self._set_price_field(tp_price, tick)
            time.sleep(0.2)
            self._click_ionic_button(exit_btn)
            self._confirm_order_dialog()
            time.sleep(0.5)
            logger.info(
                "BlackArrow: TP order placed — %s @ %.2f (%d ticks from avg %.2f)",
                exit_btn, tp_price, tp_ticks, avg_price,
            )

        # ── 6. Place SL order ────────────────────────────────────────────
        if sl_ticks:
            sl_price = self._snap_to_tick(
                avg_price - sl_ticks * tick if side_lower == "buy"
                else avg_price + sl_ticks * tick,
                tick,
            )
            self._set_price_field(sl_price, tick)
            time.sleep(0.2)
            self._click_ionic_button(exit_btn)
            self._confirm_order_dialog()
            time.sleep(0.5)
            logger.info(
                "BlackArrow: SL order placed — %s @ %.2f (%d ticks from avg %.2f)",
                exit_btn, sl_price, sl_ticks, avg_price,
            )

        logger.info("BlackArrow: order complete.")
        return True

    # ── Order-panel helpers ─────────────────────────────────────────────

    @staticmethod
    def _snap_to_tick(price: float, tick_size: float) -> float:
        """Round price to the nearest valid tick boundary.

        Uses integer arithmetic to avoid floating-point drift:
            snap(28801.123, 0.25) -> 28801.25
            snap(28801.0,   0.25) -> 28801.0
        """
        return round(round(price / tick_size) * tick_size, 10)

    def _set_price_field(self, price: float, tick_size: float = 0.25) -> None:
        """Set the Price input in the main order panel using a React-aware setter.

        Decimal places are derived from the tick size so the platform always
        receives a properly-formatted price (e.g. "28801.25" not "28801.2500").
        """
        # Number of decimal places = decimal places in tick_size string
        decimals = len(str(tick_size).rstrip('0').split('.')[-1]) if '.' in str(tick_size) else 0
        try:
            self._driver.execute_script("""
                (function(price, decimals) {
                    var setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value'
                    ).set;
                    function fire(el, v) {
                        setter.call(el, v);
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                    }
                    // Strategy 1: input with aria-label / placeholder mentioning "price"
                    var inp = document.querySelector(
                        'input[aria-label*="price" i], input[placeholder*="price" i]'
                    );
                    // Strategy 2: label "Price" → its associated input
                    if (!inp) {
                        var labels = document.querySelectorAll('label');
                        for (var lbl of labels) {
                            if (lbl.textContent.trim().toLowerCase() === 'price') {
                                var id = lbl.htmlFor;
                                inp = (id && document.getElementById(id))
                                      || lbl.querySelector('input')
                                      || (lbl.parentElement
                                          && lbl.parentElement.querySelector('input'));
                                break;
                            }
                        }
                    }
                    // Strategy 3: first visible numeric input in the panel
                    if (!inp) {
                        var all = Array.from(document.querySelectorAll(
                            'input[type="number"], input[type="text"]'
                        ));
                        inp = all.find(function(i) {
                            var r = i.getBoundingClientRect();
                            return r.width > 30 && r.height > 10;
                        });
                    }
                    if (inp) fire(inp, price.toFixed(decimals));
                })(arguments[0], arguments[1]);
            """, price, decimals)
        except Exception as e:
            logger.warning("_set_price_field: %s", e)

    def _set_qty_field(self, qty: int) -> None:
        """Set the Qty input in the main order panel using a React-aware setter."""
        try:
            self._driver.execute_script("""
                (function(qty) {
                    var setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value'
                    ).set;
                    function fire(el, v) {
                        setter.call(el, v);
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                    }
                    // Strategy 1: input with aria-label / placeholder mentioning "qty"
                    var inp = document.querySelector(
                        'input[aria-label*="qty" i], input[placeholder*="qty" i], '
                        + 'input[aria-label*="quantity" i]'
                    );
                    // Strategy 2: label "Qty" → its associated input
                    if (!inp) {
                        var labels = document.querySelectorAll('label');
                        for (var lbl of labels) {
                            var t = lbl.textContent.trim().toLowerCase();
                            if (t === 'qty' || t === 'quantity') {
                                var id = lbl.htmlFor;
                                inp = (id && document.getElementById(id))
                                      || lbl.querySelector('input')
                                      || (lbl.parentElement
                                          && lbl.parentElement.querySelector('input'));
                                break;
                            }
                        }
                    }
                    // Strategy 3: second visible numeric input (Price is first)
                    if (!inp) {
                        var all = Array.from(document.querySelectorAll(
                            'input[type="number"], input[type="text"]'
                        )).filter(function(i) {
                            var r = i.getBoundingClientRect();
                            return r.width > 30 && r.height > 10;
                        });
                        if (all.length >= 2) inp = all[1];
                    }
                    if (inp) fire(inp, String(qty));
                })(arguments[0]);
            """, qty)
        except Exception as e:
            logger.warning("_set_qty_field: %s", e)

    def _get_avg_price(self) -> Optional[float]:
        """Read the Avg (fill price) from the position panel.

        Finds the 'Avg' label leaf node, then locates the price node at the
        SAME y-coordinate (same row).  Returns None when flat ($ 0.00 or not found).
        """
        try:
            text = self._driver.execute_script(r"""
                var all = Array.from(document.querySelectorAll('*'));
                // First pass: find the 'Avg' label and its y position
                var avgEl = null, avgY = -1;
                for (var el of all) {
                    if (el.children.length > 0) continue;
                    if (el.textContent.trim() !== 'Avg') continue;
                    var r = el.getBoundingClientRect();
                    if (r.width === 0) continue;
                    avgEl = el;
                    avgY  = r.y;
                    break;
                }
                if (!avgEl) return null;
                // Second pass: find a price node on the same row (within 5px)
                for (var n of all) {
                    if (n === avgEl || n.children.length > 0) continue;
                    var nr = n.getBoundingClientRect();
                    if (Math.abs(nr.y - avgY) > 5) continue;
                    var t = n.textContent.trim();
                    // Match "$ 28,776.00" format; skip $0.00 (flat / no position)
                    if (/^\$\s*[\d,]+\.\d{2}$/.test(t) && t !== '$ 0.00') return t;
                }
                return null;
            """)
            if text:
                num = re.sub(r"[^\d.]", "", text)
                return float(num) if num else None
        except Exception as e:
            logger.warning("_get_avg_price: %s", e)
        return None

    def close_all(self, symbol: str = "NQFUT") -> bool:
        if not self._driver:
            return False
        for label in ("Close Position", "Close All"):
            try:
                btns = self._driver.find_elements(By.XPATH,
                    f'//button[contains(normalize-space(),"{label}")]')
                if btns and btns[0].is_enabled():
                    btns[0].click()
                    self._confirm_order_dialog()
                    time.sleep(ORDER_SETTLE)
                    logger.info("BlackArrow: %s clicked.", label)
                    return True
            except Exception:
                pass
        logger.info("BlackArrow: no open position found.")
        return False

    def get_account_balance(self) -> Optional[float]:
        if not self._driver:
            return None
        try:
            text = self._driver.execute_script("""
                const els = document.querySelectorAll('nav *');
                for (const el of els) {
                    if (el.children.length === 0) {
                        const t = el.textContent.trim();
                        if (/^\\$ [\\d,]+\\.\\d{2}$/.test(t)) return t;
                    }
                }
                return null;
            """)
            if text:
                num = re.sub(r"[^\d.]", "", text)
                return float(num) if num else None
        except Exception as e:
            logger.warning("get_account_balance: %s", e)
        return None

    def get_account_stats(self) -> dict:
        if self._driver:
            try:
                return self._get_stats()
            except Exception as e:
                logger.warning("get_account_stats: %s", e)
        bal = self.get_account_balance()
        return {"Balance": f"${bal:,.2f}" if bal is not None else "N/A"}

    def is_connected(self) -> bool:
        return self._connected

    def buy_market(self, symbol, qty=1, tp=None, sl=None, expected_account=None):
        """Convenience wrapper — delegates to place_order(side='buy')."""
        return self.place_order(symbol, side="buy", qty=qty, tp_ticks=tp, sl_ticks=sl)

    def sell_market(self, symbol, qty=1, tp=None, sl=None, expected_account=None):
        """Convenience wrapper — delegates to place_order(side='sell')."""
        return self.place_order(symbol, side="sell", qty=qty, tp_ticks=tp, sl_ticks=sl)

    # ================================================================== #
    # Selenium helpers
    # ================================================================== #

    def _init_driver(self) -> webdriver.Chrome:
        """Launch system Chrome with Tradovate-style anti-detection options."""
        opts = Options()

        # Persistent profile — keeps login + session alive between runs
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", self.email)
        profile_dir = os.path.join(tempfile.gettempdir(), "blackarrow_profiles", safe)
        os.makedirs(profile_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={profile_dir}")
        logger.info("[CHROME] BlackArrow profile: %s", profile_dir)

        if self.headless:
            opts.add_argument("--headless=new")

        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-crash-reporter")
        opts.add_argument("--disable-logging")
        opts.add_argument("--log-level=3")
        opts.add_argument("--silent")
        opts.add_argument("--disable-features=TranslateUI,MediaRouter")
        opts.add_argument("--disable-component-update")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-backgrounding-occluded-windows")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-plugins")
        opts.add_argument("--disable-background-networking")
        opts.add_argument("--disable-default-apps")
        opts.add_argument("--disable-sync")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--disable-software-rasterizer")

        # Anti-detection — removes "Chrome is being controlled by automated software" banner
        opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--disable-blink-features=AutomationControlled")

        opts.add_experimental_option("prefs", {
            "profile.default_content_setting_values": {"popups": 2, "notifications": 2},
            "profile.default_content_settings.images": 1,
        })

        # Remote-debugging port — lets probe scripts and diagnostics attach
        # to the running browser without restarting it.
        opts.add_argument(f"--remote-debugging-port={DEBUG_PORT}")
        # Allow CDP WebSocket connections from any localhost origin
        opts.add_argument("--remote-allow-origins=*")

        driver = webdriver.Chrome(options=opts)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        return driver

    def _has_login_form(self, driver: webdriver.Chrome) -> bool:
        try:
            # Regular inputs OR Ionic ion-input components (Nelogica/Capacitor app)
            return bool(
                driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]') or
                len(driver.find_elements(By.TAG_NAME, 'ion-input')) >= 2
            )
        except Exception:
            return False

    def _platform_ready(self, driver: webdriver.Chrome) -> bool:
        """Return True when the chart canvas or trading panel is visible."""
        try:
            return bool(
                driver.find_elements(By.TAG_NAME, "canvas") or
                driver.find_elements(By.CSS_SELECTOR, '[class*="chart" i], [class*="trading-panel" i]')
            )
        except Exception:
            return False

    def _set_qty(self, qty: int):
        """Legacy alias for _set_qty_field."""
        self._set_qty_field(qty)

    def _confirm_order_dialog(self):
        """Click OK/Confirm on any order confirmation modal."""
        try:
            btns = WebDriverWait(self._driver, CONFIRM_WAIT).until(
                EC.presence_of_all_elements_located((By.XPATH,
                    '//button[normalize-space()="OK" or normalize-space()="Confirm" or normalize-space()="Yes"]'))
            )
            if btns:
                btns[0].click()
                logger.debug("Order confirmation dismissed.")
        except Exception:
            logger.debug("No confirmation dialog.")

    def _read_account_id(self) -> Optional[str]:
        """Extract the numeric account ID from the nav-bar header.

        The header shows:  Simulador  1252252 - harry@gmail.com  D...  USD  49,997.50
        We look for a standalone token of 5-10 digits that appears before " - email".
        """
        try:
            acct = self._driver.execute_script(r"""
                var els = Array.from(document.querySelectorAll('nav *'));
                for (var el of els) {
                    if (el.children.length > 0) continue;
                    var t = el.textContent.trim();
                    // Match "1252252 - user@example.com" pattern
                    var m = t.match(/^(\d{5,10})\s*-\s*.+@/);
                    if (m) return m[1];
                    // Also match a bare numeric token between 5-10 digits
                    if (/^\d{5,10}$/.test(t)) return t;
                }
                return null;
            """)
            return acct or None
        except Exception as e:
            logger.debug("_read_account_id: %s", e)
            return None

    def _get_stats(self) -> dict:
        """Scrape Balance, MLL, SOD Balance and DailyPnL from the platform."""
        driver = self._driver
        if not driver:
            return {}
        stats = {}
        if self.account_id:
            stats["AccountId"] = self.account_id

        # Balance from nav bar
        try:
            text = driver.execute_script("""
                const els = document.querySelectorAll('nav *');
                for (const el of els) {
                    if (el.children.length === 0) {
                        const t = el.textContent.trim();
                        if (/^\\$ [\\d,]+\\.\\d{2}$/.test(t)) return t;
                    }
                }
                return null;
            """)
            if text:
                stats["Balance"] = text
        except Exception:
            pass

        # Stats from .info > span.key + span.value pairs
        for label, key in (
            ("Daily PnL",    "DailyPnL"),
            ("Open PnL",     "OpenPnL"),
            ("Margin",       "Margin"),
            ("MLL",          "MLL"),
            ("Max Loss",     "MLL"),
            ("Max Drawdown", "MLL"),
            ("DD Limit",     "MLL"),
            ("SOD Balance",  "SOD Balance"),
            ("Start Balance","SOD Balance"),
        ):
            if key in stats:
                continue
            try:
                val = driver.execute_script("""
                    (function(label) {
                        const infos = document.querySelectorAll('.info');
                        for (const info of infos) {
                            const key = info.querySelector('span.key');
                            const val = info.querySelector('span.value');
                            if (key && val && key.textContent.trim() === label) {
                                return val.textContent.trim();
                            }
                        }
                        return null;
                    })(arguments[0]);
                """, label)
                if val:
                    stats[key] = val
            except Exception:
                pass

        logger.debug("BlackArrow stats: %s", stats)
        return stats


# ================================================================== #
# Factory
# ================================================================== #

def create_connector(config: dict) -> BlackArrowConnector:
    return BlackArrowConnector(
        email=config["email"],
        password=config["password"],
        account_id=config.get("account_id", ""),
        headless=config.get("headless", False),
    )
 
