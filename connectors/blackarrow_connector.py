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
  Balance: leaf <nav *> node matching /^\$ [\d,]+\.\d{2}$/
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
CONFIRM_WAIT     = 8      # seconds for confirmation dialogs
ORDER_SETTLE     = 2.0    # seconds after placing an order


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
        if not self._driver or not self._connected:
            raise RuntimeError("BlackArrow not connected — open the broker panel and click Connect first")

        side_lower  = side.lower()
        use_bracket = (tp_ticks is not None) or (sl_ticks is not None)
        logger.info("BlackArrow: placing %s %s qty=%d tp=%s sl=%s",
                    side_lower, symbol, qty, tp_ticks, sl_ticks)

        self._set_qty(qty)

        if use_bracket:
            self._configure_bracket(tp_ticks or 0, sl_ticks or 0)

        # BlackArrow ORDER panel shows dynamic text like "BUY +6 @ MARKET" / "SELL -6 @ MARKET".
        # Use contains() so the quantity embedded in the label doesn't break matching.
        # Also try ion-button (Ionic/Capacitor wrapper) and fallback to aria-label.
        kw = "BUY" if side_lower == "buy" else "SELL"
        try:
            btns = self._driver.find_elements(
                By.XPATH,
                f'//button[contains(translate(normalize-space(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"{kw}") '
                f'and contains(translate(normalize-space(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"MARKET")]'
            )
            if not btns:
                # Fallback: ion-button via JS click helper
                clicked = self._click_ionic_button(kw)
                if not clicked:
                    raise RuntimeError(f"BlackArrow: no '{kw} @ MARKET' button found — is the Order panel open?")
            else:
                btns[0].click()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"BlackArrow: order click failed: {e}") from e

        self._confirm_order_dialog()
        time.sleep(ORDER_SETTLE)
        logger.info("BlackArrow: order complete.")
        return True

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
        driver = self._driver
        try:
            driver.execute_script("""
                (function(qty) {
                    const inputs = document.querySelectorAll('input[type="number"], input[class*="qty" i], input[class*="quantity" i]');
                    for (const inp of inputs) {
                        const r = inp.getBoundingClientRect();
                        if (r.width > 20 && r.height > 10) {
                            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                            setter.call(inp, qty);
                            inp.dispatchEvent(new Event('input',  { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            break;
                        }
                    }
                })(arguments[0]);
            """, qty)
        except Exception as e:
            logger.warning("_set_qty: %s", e)

    def _configure_bracket(self, tp_ticks: int, sl_ticks: int):
        driver = self._driver
        try:
            # Open bracket dropdown and select <Custom>
            try:
                dropdown = driver.find_elements(By.CSS_SELECTOR,
                    '[class*="bracket" i] [class*="dropdown" i], [class*="bracketType" i]')
                if dropdown:
                    dropdown[0].click()
                    time.sleep(0.3)
                    custom = driver.find_elements(By.XPATH, '//*[normalize-space()="<Custom>"]')
                    if custom:
                        custom[0].click()
                        time.sleep(0.3)
            except Exception:
                pass

            # Select Ticks unit
            try:
                driver.execute_script("""
                    const labels = document.querySelectorAll('[class*="bracket" i] label, [class*="graphic-order" i] label');
                    for (const lbl of labels) {
                        if (lbl.textContent.trim().toLowerCase() === 'ticks') { lbl.click(); return; }
                    }
                """)
            except Exception:
                pass

            # Set TP (Gain) and SL (Loss) values
            driver.execute_script("""
                (function(gain, loss) {
                    const bracket = document.querySelector(
                        '[class*="graphic-order__bracket" i], [class*="bracket-body" i], [class*="bracketBody" i]'
                    );
                    if (!bracket) return;
                    const inputs = bracket.querySelectorAll('input');
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    function sv(el, v) {
                        setter.call(el, String(v));
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    if (inputs[0]) sv(inputs[0], gain);
                    if (inputs[1]) sv(inputs[1], loss);
                })(arguments[0], arguments[1]);
            """, tp_ticks, sl_ticks)
        except Exception as e:
            logger.warning("_configure_bracket: %s", e)

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

    def _get_stats(self) -> dict:
        """Scrape Balance, MLL, SOD Balance and DailyPnL from the platform."""
        driver = self._driver
        if not driver:
            return {}
        stats = {}

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
 
