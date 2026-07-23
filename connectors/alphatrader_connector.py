"""
alphatrader_connector.py — Selenium + REST connector for Alpha Futures' platform.

Alpha Futures migrated from Tradovate to Alpha Trader (futures.alphatrader.com).

Auth:      POST https://apiv2.alphatrader.com/api/v1/auth/login/  -> Firebase JWT
Browser:   Selenium (system Chrome, same anti-detection approach as TradovateAccount)
Orders:    Selenium UI clicks on the T4-powered web platform
Cancel:    POST https://apiv2.alphatrader.com/api/v1/t4/trading/cancel-all/
Accounts:  GET  https://apiv2.alphatrader.com/api/v1/t4/accounts/

USAGE:
    conn = AlphaTraderConnector(email="user@example.com", password="secret")
    conn.connect()
    conn.place_order("NQ", side="buy", qty=2, tp_ticks=202, sl_ticks=175)
    conn.close_all("NQ")
    conn.disconnect()
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import time
from typing import Optional

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
API_BASE      = "https://apiv2.alphatrader.com/api/v1"
PLATFORM_URL  = "https://futures.alphatrader.com/"
DEFAULT_WAIT  = 25      # seconds
ORDER_SETTLE  = 2.0     # seconds after placing an order
TOKEN_REFRESH = 300     # refresh token this many seconds before expiry

# Tradovate symbol -> Alpha Trader contract_id
SYMBOL_MAP: dict[str, str] = {
    "NQ": "NQ",   "NQU6": "NQ",  "NQM6": "NQ",  "NQH6": "NQ",  "NQZ6": "NQ",
    "NQU5": "NQ", "NQM5": "NQ",  "NQH5": "NQ",  "NQZ5": "NQ",
    "MNQ": "MNQ", "MNQU6": "MNQ","MNQM6": "MNQ","MNQH6": "MNQ","MNQZ6": "MNQ",
    "ES":  "ES",  "ESU6": "ES",  "ESM6": "ES",  "ESH6": "ES",  "ESZ6": "ES",
    "MES": "MES", "MESU6": "MES","MESM6": "MES",
    "GC":  "GC",  "GCM6": "GC", "GCQ6": "GC",  "GCZ6": "GC",
    "MGC": "MGC", "MGCM6": "MGC","MGCQ6": "MGC",
    "CL":  "CL",  "CLM6": "CL", "CLN6": "CL",
}

TICK_SIZE: dict[str, float] = {
    "NQ": 0.25, "MNQ": 0.25,
    "ES": 0.25, "MES": 0.25,
    "GC": 0.10, "MGC": 0.10,
    "CL": 0.01,
}

# Exact names as they appear in the AlphaTrader CONTRACTS dropdown list
CONTRACT_DISPLAY: dict[str, str] = {
    "NQ":  "E-mini NASDAQ",
    "MNQ": "E-mini Micro NASDAQ",
    "ES":  "E-mini S&P 500",
    "MES": "E-mini Micro S&P 500",
    "GC":  "Gold",
    "MGC": "E-micro Gold",
    "CL":  "E-mini Crude Oil",
    "RTY": "E-mini Russell 2000",
    "MYM": "E-mini Micro Dow",
    "YM":  "E-mini Dow",
}


def _map_symbol(sym: str) -> str:
    s = sym.strip().upper()
    return SYMBOL_MAP.get(s, re.sub(r"[A-Z]\d+$", "", s) or s)


# ================================================================== #
# Main connector class
# ================================================================== #

class AlphaTraderConnector:
    """
    Selenium-based connector for futures.alphatrader.com.

    Uses the same system-Chrome + anti-detection approach as TradovateAccount
    so no "Test" / "Chrome is controlled by automation" banner appears.
    REST API handles authentication and account lookups; Selenium handles
    the order placement UI.
    """

    def __init__(self, email: str, password: str, headless: bool = False):
        self.email    = email
        self.password = password
        self.headless = headless

        # Auth
        self._id_token:      Optional[str]   = None
        self._refresh_token: Optional[str]   = None
        self._token_exp:     float           = 0.0

        # Account
        self._account_uuid: Optional[str] = None
        self._account_name: Optional[str] = None

        # Selenium
        self._driver:    Optional[webdriver.Chrome] = None
        self._connected: bool = False

    # ================================================================== #
    # Public API
    # ================================================================== #

    def connect(self) -> bool:
        """Authenticate via REST, then open the platform in Chrome and log in."""
        # 1. REST auth
        try:
            self._rest_login()
        except Exception as e:
            logger.error("Alpha Trader REST login failed: %s", e)
            return False

        # 2. Fetch account info
        try:
            accounts = self._rest_get_accounts() or []
            if accounts:
                default = next((a for a in accounts if a.get("is_default")), accounts[0])
                self._account_uuid = default.get("account_id")
                self._account_name = default.get("account_name")
                logger.info("Alpha Trader: account %s (%s)", self._account_name, self._account_uuid)
        except Exception as e:
            logger.warning("Alpha Trader: account fetch failed: %s", e)

        # 3. Launch Chrome
        try:
            self._driver = self._init_driver()
        except Exception as e:
            logger.error("Alpha Trader: Chrome launch failed: %s", e)
            return False

        # 4. Navigate and auto-login
        try:
            self._driver.get(PLATFORM_URL)
            wait = WebDriverWait(self._driver, DEFAULT_WAIT)

            # Wait for either the login form or the platform to be ready
            wait.until(lambda d: "/signin" in d.current_url or self._platform_ready(d))

            if "/signin" in self._driver.current_url:
                logger.info("Alpha Trader: filling login form...")
                email_field = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Email"]'))
                )
                email_field.clear()
                email_field.send_keys(self.email)

                pwd_field = self._driver.find_element(By.CSS_SELECTOR, 'input[placeholder="Password"]')
                pwd_field.clear()
                pwd_field.send_keys(self.password)

                login_btn = self._driver.find_element(
                    By.XPATH, '//button[normalize-space()="Login"]'
                )
                login_btn.click()
                logger.info("Alpha Trader: login submitted, waiting for platform...")

            # Wait for the dashboard (balance header)
            wait.until(lambda d: self._platform_ready(d))
            self._connected = True
            logger.info("Alpha Trader: platform ready.")

            # Read account name from DOM if not set via REST
            if not self._account_name:
                self._account_name = self._read_account_name()

            # Select the correct account in the UI (accountSelectorWrapper)
            self._select_ui_account()

            # Open the Trade Panel via the left sidebar icon
            self._open_trade_panel()

        except Exception as e:
            logger.error("Alpha Trader: platform failed to load: %s", e)
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
        logger.info("Alpha Trader: disconnected.")

    def place_order(
        self,
        symbol:           str,
        side:             str,
        qty:              int            = 1,
        tp_ticks:         Optional[int] = None,
        sl_ticks:         Optional[int] = None,
        expected_account: Optional[str] = None,
    ) -> bool:
        if not self._driver or not self._connected:
            raise RuntimeError("AlphaTrader not connected — open the broker panel and click Connect first")

        # ── Account guard: switch if the active account doesn't match expected ──
        if expected_account:
            try:
                active = self.get_active_account() or ""
                if expected_account.upper() not in active.upper():
                    logger.info(
                        "AlphaTrader: active account %r ≠ expected %r — switching",
                        active, expected_account,
                    )
                    switched = self.switch_account(expected_account)
                    if not switched:
                        raise RuntimeError(
                            f"AlphaTrader: could not switch to account '{expected_account}' "
                            f"(active: {active!r})"
                        )
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("AlphaTrader: account guard failed: %s", e)

        contract_id = _map_symbol(symbol)
        tick_size   = TICK_SIZE.get(contract_id, 0.25)
        side_lower  = side.lower()
        use_bracket = (tp_ticks is not None) or (sl_ticks is not None)

        logger.info("AlphaTrader: placing %s %s qty=%d tp=%s sl=%s",
                    side_lower, contract_id, qty, tp_ticks, sl_ticks)

        self._switch_contract(contract_id)
        time.sleep(0.3)  # let the order panel settle after a contract switch
        self._set_qty(qty)

        if use_bracket:
            entry = self._get_current_price(side_lower) or 0.0
            tp_price: Optional[float] = None
            sl_price: Optional[float] = None
            if side_lower == "buy":
                if tp_ticks: tp_price = entry + tp_ticks * tick_size
                if sl_ticks: sl_price = entry - sl_ticks * tick_size
            else:
                if tp_ticks: tp_price = entry - tp_ticks * tick_size
                if sl_ticks: sl_price = entry + sl_ticks * tick_size
            if tp_price is not None:
                tp_price = round(round(tp_price / tick_size) * tick_size, 4)
            if sl_price is not None:
                sl_price = round(round(sl_price / tick_size) * tick_size, 4)
            self._configure_bracket(tp_price, sl_price)
        else:
            self._disable_bracket()

        # AlphaTrader ORDER panel shows dynamic text like "BUY +2 @ MARKET" / "SELL -2 @ MARKET".
        # Use contains() so the quantity in the label doesn't break matching.
        kw = "BUY" if side_lower == "buy" else "SELL"
        try:
            # Prefer the order-form button "BUY +N @ MARKET" (contains "@") over the
            # DOM-ladder button "BUY +N MARKET" (no "@").  Both are ant-btn elements.
            clicked = self._driver.execute_script(f"""
                var kw = '{kw}';
                // First pass: prefer buttons containing '@ MARKET'
                var btns = Array.from(document.querySelectorAll('button'));
                var b = btns.find(function(b) {{
                    var t = (b.innerText||'').toUpperCase();
                    return t.includes(kw) && t.includes('@ MARKET') && b.offsetParent !== null;
                }});
                if (b) {{ b.click(); return '@ MARKET clicked: ' + (b.innerText||'').trim(); }}
                // Second pass: any MARKET button
                b = btns.find(function(b) {{
                    var t = (b.innerText||'').toUpperCase();
                    return t.includes(kw) && t.includes('MARKET') && b.offsetParent !== null;
                }});
                if (b) {{ b.click(); return 'MARKET clicked: ' + (b.innerText||'').trim(); }}
                return null;
            """)
            if not clicked:
                logger.error("AlphaTrader: SELL button not found.")
                raise RuntimeError(f"AlphaTrader: '{kw} @ MARKET' button not found — is the Trade Panel open?")
            logger.info("AlphaTrader: %s", clicked)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"AlphaTrader: order click failed: {e}") from e

        time.sleep(ORDER_SETTLE)
        logger.info("AlphaTrader: order complete.")
        return True

    def close_all(self, symbol: str = "NQ") -> bool:
        if not self._driver:
            return False
        self._switch_contract(_map_symbol(symbol))
        for label in ("CLOSE POSITION", "FLATTEN ALL"):
            try:
                btns = self._driver.find_elements(
                    By.XPATH, f'//button[contains(normalize-space(),"{label}")]')
                if btns and btns[0].is_enabled():
                    btns[0].click()
                    time.sleep(ORDER_SETTLE)
                    return True
            except Exception:
                pass
        return False

    def flatten_all(self) -> bool:
        return self._rest_cancel_all()

    def get_account_balance(self) -> Optional[float]:
        # 1. Try DOM first (works without REST credentials in probe mode)
        if self._driver:
            try:
                raw = self._driver.execute_script("""
                    var labels = Array.from(document.querySelectorAll('*')).filter(function(el) {
                        return el.childElementCount === 0 &&
                               (el.textContent || '').trim() === 'Current Balance';
                    });
                    for (var i = 0; i < labels.length; i++) {
                        var parent = labels[i].parentElement;
                        if (!parent) continue;
                        var siblings = Array.from(parent.children);
                        for (var j = 0; j < siblings.length; j++) {
                            var t = (siblings[j].textContent || '').replace(/[$,]/g,'').trim();
                            var v = parseFloat(t);
                            if (!isNaN(v) && v > 1000) return v;
                        }
                    }
                    return null;
                """)
                if raw is not None:
                    return float(raw)
            except Exception:
                pass
        # 2. Fall back to REST
        data = self._rest_get_accounts()
        if data:
            acct = next((a for a in data if a.get("account_id") == self._account_uuid),
                        data[0] if data else None)
            if acct:
                return float(acct.get("available_balance", acct.get("balance", 0)))
        return None

    def get_account_info(self) -> Optional[dict]:
        data = self._rest_get_accounts()
        if data:
            return next((a for a in data if a.get("account_id") == self._account_uuid),
                        data[0] if data else None)
        return None

    def get_account_size_label(self, firm: str = "AlphaFutures") -> Optional[str]:
        """
        Return the account-size tier label ("50k", "100k", "150k") for the
        active account by reading the available_balance from the REST API and
        rounding to the nearest standard tier for the given firm.

        Strategy:
          - Use the active account's current balance.
          - For evaluation accounts the balance stays close to the initial
            account size, so rounding gives the correct tier.
          - For funded accounts the balance may have grown; we still use the
            closest tier, which is the tier the account was originally funded at.

        Returns None if the balance cannot be read or no matching tier found.
        """
        # Pull size tiers from PropFirmManager if available, else use defaults
        _FIRM_TIERS: dict = {
            "AlphaFutures":    [50_000, 100_000, 150_000],
            "AlphaFutures GC": [50_000, 100_000, 150_000],
            "TopStep":         [50_000, 100_000, 150_000],
            "TopStepX":        [50_000, 100_000, 150_000],
        }
        tiers = _FIRM_TIERS.get(firm, [50_000, 100_000, 150_000])

        balance = self.get_account_balance()
        if balance is None:
            return None

        closest = min(tiers, key=lambda t: abs(balance - t))
        label = f"{closest // 1_000}k"
        logger.info("AlphaTrader: account size detected → %s (balance=%.2f, firm=%s)",
                    label, balance, firm)
        return label

    def get_active_account(self) -> Optional[str]:
        """Return the active account name (e.g. 'ADVEV2026060800605').

        Always reads fresh from the DOM so it stays accurate after a
        switch_account() call made by another thread or the UI.
        Strips react-select wrapper text like 'option … selected.\n…'.
        """
        raw = None
        if self._driver:
            try:
                raw = self._driver.execute_script(
                    "var w=document.querySelector('.accountSelectorWrapper');"
                    " return w ? (w.innerText||w.textContent||'').trim() : '';"
                ) or ""
                # react-select produces: "option evaluation - ADVEV…, selected.\nevaluation - ADVEV…"
                # Extract the ADVEV… id via regex
                import re as _re
                m = _re.search(r'[A-Z]{2,}[A-Z0-9]{8,}', raw)
                if m:
                    self._account_name = m.group(0)
                    return self._account_name
                # Fallback: first non-empty line after stripping "option" prefix
                for line in raw.splitlines():
                    line = line.strip()
                    if line and not line.lower().startswith("option ") and "selected" not in line.lower():
                        self._account_name = line
                        return self._account_name
            except Exception:
                pass
        # Last resort: cached value
        if not self._account_name and self._driver:
            self._account_name = self._read_account_name()
        return self._account_name

    def switch_account(self, account_name: str) -> bool:
        """
        Switch the active account in the platform UI after connect().

        account_name: a substring of the account name shown in the selector
                      (e.g. "ADVEV2026060800605" or just the numeric ID).
        Returns True if the selector confirmed the switch, False otherwise.
        """
        if not self._driver or not self._connected:
            raise RuntimeError("AlphaTrader not connected")

        # Read the balance BEFORE switching so we can detect when it updates
        balance_before = self.get_account_balance()

        self._account_name = account_name
        self._select_ui_account()

        # Confirm by checking the selector text AND waiting for balance to update
        try:
            current = self._driver.execute_script(
                "var w=document.querySelector('.accountSelectorWrapper'); "
                "return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : '';"
            ) or ""
            name_ok = account_name.upper() in current.upper()

            # Poll for up to 5 s for the stats panel to reload for the new account
            balance_after = None
            deadline = time.time() + 5
            while time.time() < deadline:
                bal = self.get_account_balance()
                if bal is not None and bal != balance_before:
                    balance_after = bal
                    break
                time.sleep(0.4)
            if balance_after is None:
                balance_after = self.get_account_balance()

            if name_ok:
                # Extract the bare account ID (strips "evaluation - " / "funded - " etc.)
                clean_id = re.search(r'[A-Z]{2,}[A-Z0-9]{8,}', current)
                self._account_name = clean_id.group(0) if clean_id else current
                logger.info(
                    "AlphaTrader: switched account → %s  balance before=%.2f after=%.2f",
                    self._account_name, balance_before or 0, balance_after or 0,
                )
                return True
            logger.warning(
                "AlphaTrader: switch_account: expected '%s', selector shows '%s'",
                account_name, current,
            )
        except Exception as e:
            logger.warning("AlphaTrader: switch_account confirm failed: %s", e)
        return False

    def get_account_stats(self) -> dict:
        if self._driver:
            try:
                return self._get_stats()
            except Exception:
                pass
        bal = self.get_account_balance()
        return {"Balance": f"${bal:,.2f}" if bal is not None else "N/A"}

    def is_connected(self) -> bool:
        return self._connected

    # ================================================================== #
    # REST helpers
    # ================================================================== #

    def _ensure_token(self):
        if self._id_token and time.time() < self._token_exp - TOKEN_REFRESH:
            return
        if self._refresh_token:
            try:
                self._rest_refresh_token()
                return
            except Exception:
                pass
        self._rest_login()

    def _rest_login(self):
        resp = requests.post(
            f"{API_BASE}/auth/login/",
            json={"email": self.email, "password": self.password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Alpha Trader login failed: {data.get('message')}")
        tokens = data["data"]["tokens"]
        self._id_token      = tokens["id_token"]
        self._refresh_token = tokens.get("refresh_token")
        self._token_exp     = time.time() + int(tokens.get("expires_in", 3600))
        logger.info("Alpha Trader REST: authenticated as %s", self.email)

    def _rest_refresh_token(self):
        resp = requests.post(
            "https://securetoken.googleapis.com/v1/token",
            params={"key": "AIzaSyD-PLACEHOLDER"},
            json={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            timeout=15,
        )
        if resp.status_code == 200:
            d = resp.json()
            self._id_token  = d.get("id_token")
            self._token_exp = time.time() + int(d.get("expires_in", 3600))
        else:
            self._rest_login()

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._id_token}", "Content-Type": "application/json"}

    def _rest_get_accounts(self) -> Optional[list]:
        try:
            r = requests.get(f"{API_BASE}/t4/accounts/", headers=self._auth_headers(), timeout=10)
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as e:
            logger.warning("get_accounts: %s", e)
            return None

    def _rest_cancel_all(self) -> bool:
        try:
            payload = {"account_id": self._account_uuid} if self._account_uuid else {}
            r = requests.post(f"{API_BASE}/t4/trading/cancel-all/",
                              headers=self._auth_headers(), json=payload, timeout=10)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning("cancel_all: %s", e)
            return False

    # ================================================================== #
    # Selenium helpers
    # ================================================================== #

    def _init_driver(self) -> webdriver.Chrome:
        """Launch system Chrome with Tradovate-style anti-detection options."""
        opts = Options()

        # Persistent profile — keeps login state between sessions
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", self.email)
        profile_dir = os.path.join(tempfile.gettempdir(), "alphatrader_profiles", safe)
        os.makedirs(profile_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={profile_dir}")
        logger.info("[CHROME] AlphaTrader profile: %s", profile_dir)

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
        opts.add_argument("--remote-debugging-port=9222")
        opts.add_argument("--remote-allow-origins=*")

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

    def _platform_ready(self, driver: webdriver.Chrome) -> bool:
        try:
            return bool(driver.find_elements(By.XPATH, '//*[contains(text(),"Current Balance")]'))
        except Exception:
            return False

    def _select_ui_account(self):
        """
        Select the correct T4 account in the accountSelectorWrapper react-select.
        Uses Selenium find_elements for reliable open/wait/click.
        """
        driver = self._driver
        target = self._account_name  # e.g. "ADVEV2026060800605"
        try:
            # Wait for the account selector wrapper to exist and be populated
            deadline = time.time() + 15
            while time.time() < deadline:
                populated = driver.execute_script(
                    "var w=document.querySelector('.accountSelectorWrapper');"
                    " return w && w.children.length > 0;"
                )
                if populated:
                    break
                time.sleep(0.5)

            if not driver.execute_script(
                "var w=document.querySelector('.accountSelectorWrapper');"
                " return w && w.children.length > 0;"
            ):
                logger.warning("Alpha Trader: accountSelectorWrapper still empty after 15s")
                return

            if not target:
                return

            # Check if the target is already selected — skip if so
            try:
                current_text = (driver.execute_script(
                    "var w=document.querySelector('.accountSelectorWrapper');"
                    " return w ? (w.innerText||w.textContent||'').trim() : '';"
                ) or "").upper()
                if target.upper() in current_text:
                    logger.info("Alpha Trader: account %r already selected, skipping UI switch", target)
                    return
            except Exception:
                pass

            # Close any already-open dropdown using Selenium Keys.ESCAPE
            try:
                from selenium.webdriver.common.keys import Keys
                parent_el = driver.find_element(By.CSS_SELECTOR, '.accountSelectorWrapper')
                parent_el.send_keys(Keys.ESCAPE)
            except Exception:
                pass
            time.sleep(1.0)

            # Open dropdown by clicking the control with real Selenium click
            ctrl_el = None
            for sel in ['.accountSelectorWrapper [class*="-control"]', '.accountSelectorWrapper']:
                try:
                    ctrl_el = driver.find_element(By.CSS_SELECTOR, sel)
                    break
                except Exception:
                    pass
            if not ctrl_el:
                logger.warning("Alpha Trader: account selector control not found")
                return

            # Use ActionChains for a real mouse click sequence
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).move_to_element(ctrl_el).pause(0.2).click(ctrl_el).perform()
            time.sleep(1.5)

            # Wait for account option elements to appear (filter by account ID pattern)
            opts = []
            all_opts = []
            opts_deadline = time.time() + 5
            while time.time() < opts_deadline:
                all_opts = driver.find_elements(
                    By.CSS_SELECTOR, '[role="option"], [class*="-option"]'
                )
                # Keep only options with ADVEV-style account IDs in their text
                opts = [
                    o for o in all_opts
                    if re.search(r'[A-Z]{2,}[A-Z0-9]{8,}', o.text or (o.get_attribute("textContent") or ""))
                ]
                if opts:
                    break
                time.sleep(0.25)

            if not opts:
                logger.warning("Alpha Trader: account option %r not found in selector (0 account opts)", target)
                return

            logger.info("Alpha Trader: _select_ui_account found %d opts, target=%r", len(opts), target)
            # Find and click the matching option
            t_upper = target.upper()
            clicked = False
            for opt in opts:
                try:
                    txt = (opt.text or opt.get_attribute("textContent") or "").upper()
                    if t_upper in txt:
                        driver.execute_script("""
                            var el = arguments[0];
                            el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                            el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                            el.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true}));
                            el.click();
                        """, opt)
                        logger.info("Alpha Trader: UI account selected: %s", target)
                        clicked = True
                        time.sleep(2.0)
                        break
                except Exception:
                    pass

            if not clicked:
                logger.warning("Alpha Trader: account option %r not found in selector", target)
                # Close dropdown if still open
                try:
                    driver.execute_script(
                        "document.querySelector('body').dispatchEvent("
                        "new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));"
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.warning("Alpha Trader: _select_ui_account failed: %s", e)

    def _open_trade_panel(self):
        """
        Click the Trade Panel icon in the left sidebar to show the order entry panel.
        Waits up to 8 s for BUY/SELL buttons to appear.
        """
        driver = self._driver
        try:
            # Click the sidebar item whose img has alt="Trade Panel"
            clicked = driver.execute_script(r"""
                var imgs = document.querySelectorAll('img[alt="Trade Panel"]');
                if (imgs.length) {
                    var el = imgs[0];
                    for (var i = 0; i < 6; i++) {
                        if (!el.parentElement) break;
                        el = el.parentElement;
                        if (el.tagName==='LI' || el.tagName==='BUTTON' || el.tagName==='A') {
                            el.click();
                            return 'clicked_' + el.tagName;
                        }
                    }
                    imgs[0].click(); return 'clicked_img';
                }
                // Fallback: any sidebar-menu-item containing "trade" in data-menu-id
                var items = document.querySelectorAll('.sidebar-menu-item[data-menu-id]');
                if (items.length > 1) { items[1].click(); return 'clicked_sidebar_item_1'; }
                return 'not_found';
            """)
            logger.info("Alpha Trader: Trade Panel sidebar click: %s", clicked)
            time.sleep(1.0)

            # Wait for BUY or SELL @ MARKET button to appear (up to 8 s)
            deadline = time.time() + 8
            while time.time() < deadline:
                found = driver.execute_script("""
                    return Array.from(document.querySelectorAll('button')).some(function(b) {
                        var t = (b.innerText||'').toUpperCase();
                        return (t.includes('BUY') || t.includes('SELL')) && t.includes('MARKET');
                    });
                """)
                if found:
                    logger.info("Alpha Trader: Trade Panel loaded — BUY/SELL @ MARKET button visible")
                    return
                time.sleep(0.5)

            # If still not found, try the first sidebar item as fallback
            logger.warning("Alpha Trader: BUY/SELL buttons not found after Trade Panel click")
            all_btns = driver.execute_script(
                "return Array.from(document.querySelectorAll('button'))"
                ".filter(b=>b.offsetParent!==null).map(b=>(b.innerText||'').trim().slice(0,60))"
            )
            logger.info("Alpha Trader: visible buttons: %s", all_btns)
        except Exception as e:
            logger.warning("Alpha Trader: _open_trade_panel failed: %s", e)

    def _switch_contract(self, contract_id: str):
        """
        Switch the active contract.
        Strategy 1: click the symbol tab at the top of the Trade Panel (fast, reliable).
        Strategy 2: click the CONTRACTS dropdown and pick the matching option.
        """
        driver = self._driver
        sym    = contract_id.upper()
        target = CONTRACT_DISPLAY.get(sym, sym)   # e.g. "E-mini NASDAQ"
        try:
            # ---- Strategy 1: symbol tab at top of Trade Panel ----
            # Tabs look like  DIV '1\nES'  DIV '2\nMNQ'  etc.
            tab_clicked = driver.execute_script("""
                var sym = arguments[0];
                var divs = Array.from(document.querySelectorAll('div'));
                for (var d of divs) {
                    if (d.offsetParent === null) continue;
                    var t = (d.innerText||d.textContent).trim();
                    // Case 1: div is exactly the symbol text — click its parent tab
                    if (t === sym) {
                        var p = d.parentElement;
                        if (p) { p.click(); return 'tab_parent:' + sym; }
                        d.click(); return 'tab_text:' + sym;
                    }
                    // Case 2: div text is "N\\nSYM" (e.g. "2\\nMNQ") — click it directly
                    var parts = t.split('\\n');
                    if (parts.length === 2 && parts[1].trim() === sym
                            && /^\\d+$/.test(parts[0].trim())) {
                        d.click(); return 'tab_div:' + t;
                    }
                }
                return false;
            """, sym)

            if tab_clicked:
                logger.info("AlphaTrader: _switch_contract via tab: %s", tab_clicked)
                time.sleep(0.6)
                # Verify the CONTRACTS field updated — use React-Select singleValue div
                cur_text = driver.execute_script("""
                    // Use lbl.parentElement (one level up = input-wrapper) to stay
                    // inside the CONTRACTS dropdown only, never the account selector.
                    var lbl = Array.from(document.querySelectorAll('label'))
                        .find(l => (l.innerText||l.textContent).trim().toUpperCase() === 'CONTRACTS');
                    if (lbl && lbl.parentElement) {
                        var sv = lbl.parentElement.querySelector('[class*="singleValue"]');
                        if (sv && sv.offsetParent !== null)
                            return (sv.innerText || sv.textContent || '').trim();
                    }
                    return '';
                """) or ""
                logger.info("AlphaTrader: CONTRACTS field after tab click: '%s'", cur_text)
                if target.upper() in cur_text.upper():
                    return   # tab did update the order form
                # Tab click fired but didn't update order form — fall through to Strategy 2
                logger.info("AlphaTrader: tab click did not change order form, trying CONTRACTS dropdown")

            # ---- Read current contract (React-Select singleValue scoped to CONTRACTS) ----
            cur_text = driver.execute_script("""
                var lbl = Array.from(document.querySelectorAll('label'))
                    .find(l => (l.innerText||l.textContent).trim().toUpperCase() === 'CONTRACTS');
                if (lbl && lbl.parentElement) {
                    var sv = lbl.parentElement.querySelector('[class*="singleValue"]');
                    if (sv && sv.offsetParent !== null)
                        return (sv.innerText || sv.textContent || '').trim();
                }
                return '';
            """) or ""
            if target.upper() in cur_text.upper():
                logger.debug("_switch_contract: already on %s (%s)", sym, cur_text)
                return

            # ---- Strategy 2: open the CONTRACTS react-select ----
            # react-select listens for mousedown (not click); use Selenium element.click()
            # which fires the full mousedown→mouseup→click sequence.
            #
            # Approach A: find the control via CONTRACTS label proximity — most reliable
            # because the Trade Panel's CONTRACTS dropdown class varies (sometimes
            # 'react-select css-b62m3t-container', sometimes 'contract-dropdown css-…').
            # Approach B: CSS scoped selectors as fallback.
            opened = False
            ctrl_el = None

            # Approach A: CONTRACTS label → parent container → [class*="-control"]
            try:
                labels = driver.find_elements(
                    By.XPATH,
                    '//label[normalize-space(.)="CONTRACTS" or '
                    'normalize-space(.)="Contracts"]'
                )
                for lbl in labels:
                    try:
                        parent = lbl.find_element(By.XPATH, "..")
                        candidates = parent.find_elements(
                            By.CSS_SELECTOR, '[class*="-control"]'
                        )
                        visible = [c for c in candidates if c.is_displayed()]
                        if visible:
                            ctrl_el = visible[0]
                            break
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("_switch_contract: label proximity search failed: %s", e)

            # Approach B: CSS scoped selectors
            if not ctrl_el:
                for scope_css in (
                    '.order-container .contract-dropdown [class*="-control"]',
                    '.order-container [class*="-control"]',
                    '.dom-wrapper .contract-dropdown [class*="-control"]',
                    '.contract-dropdown [class*="-control"]',
                ):
                    els = driver.find_elements(By.CSS_SELECTOR, scope_css)
                    visible = [e for e in els if e.is_displayed()]
                    if visible:
                        ctrl_el = visible[0]
                        break

            if ctrl_el:
                try:
                    ctrl_el.click()
                    opened = "selenium-control-click"
                except Exception as click_err:
                    logger.debug("_switch_contract: Selenium control click failed: %s", click_err)

            if not opened:
                # JS fallback: fire mousedown on the control
                opened = driver.execute_script("""
                    var cont = document.querySelector('.order-container .contract-dropdown')
                           || document.querySelector('.dom-wrapper .contract-dropdown')
                           || document.querySelector('.contract-dropdown');
                    if (!cont) return false;
                    var ctrl = cont.querySelector('[class*="-control"]');
                    if (!ctrl) { cont.click(); return 'container-click'; }
                    ['mousedown','mouseup','click'].forEach(function(ev) {
                        ctrl.dispatchEvent(new MouseEvent(ev, {bubbles:true, cancelable:true}));
                    });
                    return 'js-mousedown-control';
                """)

            if not opened:
                raise RuntimeError(
                    "AlphaTrader: CONTRACTS react-select control not found — "
                    "Trade Panel may not be open"
                )
            logger.info("AlphaTrader: CONTRACTS dropdown opened via: %s", opened)
            time.sleep(0.8)

            # ---- Find options (react-select portal) ----
            # Use Selenium find_elements which handles DOM portals
            opt_els = []
            for css in ('[role="option"]',
                        '[class*="-option"]',
                        '[id*="react-select"][id*="option"]',
                        '[class*="__option"]'):
                found = [e for e in driver.find_elements(By.CSS_SELECTOR, css)
                         if e.is_displayed()]
                if found:
                    logger.info("_switch_contract: found %d options via %r", len(found), css)
                    opt_els = found
                    break

            if not opt_els:
                # Dump all react-select IDs to help diagnose
                rs_ids = driver.execute_script("""
                    return Array.from(document.querySelectorAll('[id*="react-select"]'))
                        .map(e => e.id).slice(0,20);
                """)
                logger.info("_switch_contract: react-select IDs in DOM: %s", rs_ids)

            # ---- Click the matching option ----
            chosen = None
            for opt in opt_els:
                txt = opt.text.strip()
                if target.upper() in txt.upper():
                    # Avoid "E-mini Micro NASDAQ" when looking for "E-mini NASDAQ"
                    # but allow if target IS "E-mini Micro NASDAQ"
                    micro_target = "MICRO" in target.upper()
                    if not micro_target and "MICRO" in txt.upper():
                        continue
                    opt.click()
                    logger.info("AlphaTrader: selected contract option: %r", txt)
                    chosen = txt
                    break

            if not chosen:
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                except Exception:
                    pass
                avail = [e.text.strip() for e in opt_els[:15]]
                raise RuntimeError(
                    f"AlphaTrader: contract '{target}' ({sym}) not found. "
                    f"Available: {avail}"
                )

            time.sleep(0.5)

            # ---- Confirm (singleValue scoped to CONTRACTS label parent only) ----
            cur_text = driver.execute_script("""
                var lbl = Array.from(document.querySelectorAll('label'))
                    .find(l => (l.innerText||l.textContent).trim().toUpperCase() === 'CONTRACTS');
                if (lbl && lbl.parentElement) {
                    var sv = lbl.parentElement.querySelector('[class*="singleValue"]');
                    if (sv && sv.offsetParent !== null)
                        return (sv.innerText || sv.textContent || '').trim();
                }
                return '';
            """) or ""
            if cur_text and target.upper() not in cur_text.upper():
                raise RuntimeError(
                    f"AlphaTrader: contract switch to '{sym}' failed — "
                    f"platform still shows '{cur_text}'"
                )
            logger.info("AlphaTrader: contract confirmed as '%s'", cur_text)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"AlphaTrader: _switch_contract failed: {e}") from e

    def _set_qty(self, qty: int):
        """
        Set the order quantity using ActionChains real browser events.

        JS element.click() does not fire the mousedown/mouseup events that React
        needs for synthetic event handling on these buttons — the same issue that
        required ActionChains for the account dropdown.  ActionChains generates
        genuine browser input events so React state updates reliably.

        Strategy: click the largest preset \u2264 qty as a base, then click '+' the
        minimum remaining number of times (e.g. qty=6 \u2192 click '5', then one '+').
        """
        driver = self._driver
        try:
            # The # OF CONTRACTS field is an Ant Design InputNumber component:
            #   input[type="text"][class*="ant-input-number-input"], width ~139 px.
            # Confirmed by visible-input diagnostic dump on 2026-07-21.
            # The tiny React-Select hidden inputs (width 1-3 px) must be excluded
            # by requiring width >= 50.
            qty_input = driver.execute_script("""
                // Primary: Ant Design InputNumber class
                var inp = Array.from(document.querySelectorAll(
                        'input[class*="ant-input-number-input"]'))
                    .find(function(el) {
                        var r = el.getBoundingClientRect();
                        return el.offsetParent !== null && r.width >= 50 && r.height >= 20
                               && el.placeholder !== '0.00';
                    });
                if (inp) return inp;
                // Fallback: any input with width >= 50 that isn't a React-Select
                //            hidden input or TP/SL placeholder
                return Array.from(document.querySelectorAll('input'))
                    .find(function(el) {
                        var r = el.getBoundingClientRect();
                        return el.offsetParent !== null
                               && r.width >= 50 && r.height >= 20
                               && el.placeholder !== '0.00'
                               && el.type !== 'checkbox' && el.type !== 'radio'
                               && el.type !== 'hidden'  && el.type !== 'search'
                               && !el.className.includes('dummyInput')
                               && !el.id.includes('react-select');
                    }) || null;
            """)

            if qty_input:
                # Step 1: React native-value setter (same as _configure_bracket TP/SL)
                before_val = driver.execute_script("return arguments[0].value;", qty_input)
                driver.execute_script("""
                    var inp = arguments[0], val = arguments[1];
                    var setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, String(val));
                    inp.dispatchEvent(new Event('input',  {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    inp.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
                """, qty_input, qty)
                time.sleep(0.1)
                after_val = driver.execute_script("return arguments[0].value;", qty_input)
                logger.info("_set_qty: native setter %s -> %s (target %s)",
                            before_val, after_val, qty)

                if str(after_val) == str(qty):
                    return   # confirmed set correctly

                # Step 2: native setter didn't stick — use ActionChains keyboard
                logger.warning(
                    "_set_qty: native setter gave '%s', falling back to keyboard", after_val)
                ActionChains(driver)\
                    .click(qty_input)\
                    .key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL)\
                    .send_keys(str(qty))\
                    .send_keys(Keys.TAB)\
                    .perform()
                time.sleep(0.2)
                final_val = driver.execute_script("return arguments[0].value;", qty_input)
                logger.info("_set_qty: after keyboard -> value='%s'", final_val)
                return

            # ── Last resort: wait for pos-btn buttons ──────────────────────────
            logger.warning("_set_qty: qty input not found — falling back to pos-btn buttons")
            preset_vals = [1, 3, 5, 10, 15]
            base = max((p for p in preset_vals if p <= qty), default=1)
            deadline = time.time() + 4.0
            base_btn = None
            while time.time() < deadline:
                base_btn = driver.execute_script(f"""
                    var btns = Array.from(document.querySelectorAll('button.pos-btn'));
                    var btn = btns.find(b => b.textContent.trim() === '{base}');
                    if (!btn) return null;
                    var r = btn.getBoundingClientRect();
                    return (r.width > 0 && r.height > 0) ? btn : null;
                """)
                if base_btn:
                    break
                time.sleep(0.15)
            if base_btn:
                ActionChains(driver).move_to_element(base_btn).pause(0.1).click(base_btn).perform()
                time.sleep(0.15)
            else:
                logger.warning("_set_qty: preset button '%s' not visible after 4 s", base)
            if base == qty:
                return
            plus_clicks = qty - base
            plus_btn = driver.execute_script("""
                var btns = Array.from(document.querySelectorAll('button.pos-btn'));
                var btn = btns.find(b => b.textContent.trim() === '+');
                if (!btn) return null;
                var r = btn.getBoundingClientRect();
                return (r.width > 0 && r.height > 0) ? btn : null;
            """)
            if plus_btn:
                for _ in range(min(plus_clicks, 30)):
                    ActionChains(driver).move_to_element(plus_btn).pause(0.05).click(plus_btn).perform()
                    time.sleep(0.08)
            else:
                logger.warning("_set_qty: '+' button not visible — qty may be wrong")
        except Exception as e:
            logger.warning("_set_qty: %s", e)

    def _get_current_price(self, side: str) -> Optional[float]:
        time.sleep(0.3)
        try:
            label = "ask" if side == "buy" else "bid"
            txt = self._driver.execute_script(f"""
                const m = document.body.innerText.match(/{label}[:\\s]+([\\d,]+\\.\\d+)/i);
                return m ? m[1].replace(/,/g,'') : null;
            """)
            if txt:
                return float(txt)
        except Exception:
            pass
        return None

    def _configure_bracket(self, tp: Optional[float], sl: Optional[float]):
        driver = self._driver
        try:
            # AlphaTrader order panel: the AutoOCO section uses a custom div toggle.
            # Structure: .bracket-toggle > .bracket-label > .bracket-checkbox
            # The TP/SL inputs (input[placeholder="0.00"]) are NOT inside .bracket-toggle —
            # they are siblings elsewhere in the order panel. Find them globally.

            def _visible_bracket_toggle():
                for el in driver.find_elements(By.CSS_SELECTOR, ".bracket-toggle"):
                    if el.is_displayed():
                        return el
                return None

            def _bracket_inputs_visible():
                """Return visible input[placeholder='0.00'] from anywhere on page."""
                return [i for i in driver.find_elements(
                    By.CSS_SELECTOR, 'input[placeholder="0.00"]')
                    if i.is_displayed()]

            toggle = _visible_bracket_toggle()
            if toggle is None:
                logger.warning("_configure_bracket: no visible bracket-toggle found")
                return

            # Check if AutoOCO is already enabled (bracket-checkbox has 'active' class)
            cb = toggle.find_elements(By.CSS_SELECTOR, ".bracket-checkbox")
            is_active = cb and "active" in (cb[0].get_attribute("class") or "")
            if not is_active:
                # Scroll into view then click the bracket-label
                label = toggle.find_elements(By.CSS_SELECTOR, ".bracket-label")
                if label:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", label[0])
                    time.sleep(0.1)
                    ActionChains(driver).move_to_element(label[0]).click().perform()
                    logger.debug("_configure_bracket: clicked bracket-label to enable")
                    time.sleep(1.0)

            visible = _bracket_inputs_visible()
            logger.info("_configure_bracket: %d TP/SL input(s) visible, tp=%s sl=%s",
                        len(visible), tp, sl)
            if len(visible) < 2:
                logger.warning("_configure_bracket: still <2 inputs after toggle, skipping")
                return

            setter_js = """
                var inp = arguments[0], val = arguments[1];
                var setter = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype, 'value').set;
                setter.call(inp, String(val));
                inp.dispatchEvent(new Event('input',  {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                inp.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
            """
            if tp is not None:
                driver.execute_script(setter_js, visible[0], tp)
            if sl is not None:
                driver.execute_script(setter_js, visible[1], sl)
        except Exception as e:
            logger.warning("_configure_bracket: %s", e)

    def _disable_bracket(self):
        driver = self._driver
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, ".bracket-toggle"):
                if el.is_displayed():
                    cb = el.find_elements(By.CSS_SELECTOR, ".bracket-checkbox")
                    if cb and "active" in (cb[0].get_attribute("class") or ""):
                        label = el.find_elements(By.CSS_SELECTOR, ".bracket-label")
                        if label:
                            label[0].click()
                            time.sleep(0.3)
                    break
        except Exception:
            pass

    def _read_account_name(self) -> Optional[str]:
        driver = self._driver
        if not driver:
            return None
        for sel in ('.accountSelectorWrapper', '[class*="singleValue"]'):
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    text = els[0].text.strip()
                    m = re.search(r'[A-Z]{2,}[A-Z0-9]{10,}', text)
                    return m.group(0) if m else (text or None)
            except Exception:
                pass
        return None

    def _get_stats(self) -> dict:
        driver = self._driver
        if not driver:
            return {}
        stats = {}
        for key, label in [
            ("Balance",          "Current Balance"),
            ("Equity",           "Equity"),
            ("DailyPnL",         "Net Daily PNL"),
            ("MLL",              "MLL"),
            ("SOD Balance",      "SOD Balance"),
            ("DistanceToMLL",    "Distance to MLL"),
        ]:
            try:
                els = driver.find_elements(By.XPATH, f'//*[normalize-space()="{label}"]')
                for el in els:
                    try:
                        children = el.find_element(By.XPATH, "..").find_elements(By.XPATH, "*")
                        if len(children) >= 2:
                            val = children[1].text.strip()
                            if val:
                                stats[key] = val
                                break
                    except Exception:
                        pass
            except Exception:
                pass
        return stats

    @staticmethod
    def _parse_dollar(s: str) -> Optional[float]:
        """Parse '$149,943.64' or '-$711.12' → float, or None on failure."""
        if not s or s in ("N/A", "", "—"):
            return None
        try:
            return float(s.replace("$", "").replace(",", "").strip())
        except Exception:
            return None

    def get_min_equity(self, account_id=None) -> Optional[dict]:
        """Return live equity / drawdown data in the same format as TradovateAccount.get_min_equity().

        Reads from the AlphaTrader header bar:
          Balance  → net_liq
          SOD Balance → net_liq_sod
          MLL      → min_equity + trailing_max_drawdown_limit
          Distance to MLL → drawdown_remaining

        Used by _apply_tp_sl_adjustments to run the SL midnight-floor and
        TMDL cap adjustments (same pipeline as Tradovate accounts).
        """
        try:
            stats = self._get_stats()
            net_liq    = self._parse_dollar(stats.get("Balance") or stats.get("Equity", ""))
            net_liq_sod = self._parse_dollar(stats.get("SOD Balance", ""))
            mll         = self._parse_dollar(stats.get("MLL", ""))
            dist_to_mll = self._parse_dollar(stats.get("DistanceToMLL", ""))

            if net_liq is None:
                return None

            # If SOD Balance not on screen, fall back to net_liq (no daily-P/L adjustment)
            if net_liq_sod is None:
                net_liq_sod = net_liq

            # MLL is the absolute hard-stop floor (trailing drawdown limit)
            tmdl = mll  # same concept
            if tmdl is None and dist_to_mll is not None:
                tmdl = net_liq - dist_to_mll

            drawdown_remaining = dist_to_mll
            if drawdown_remaining is None and tmdl is not None:
                drawdown_remaining = net_liq - tmdl

            return {
                "net_liq":                     net_liq,
                "net_liq_sod":                 net_liq_sod,
                "min_equity":                  mll,
                "trailing_max_drawdown_limit": tmdl,
                "trailing_max_drawdown":       None,
                "trailing_mode":               "trailing",
                "drawdown_remaining":          drawdown_remaining,
                "max_net_liq":                 None,
            }
        except Exception as e:
            logger.warning("get_min_equity: %s", e)
            return None


# ================================================================== #
# Factory
# ================================================================== #

def create_connector(config: dict) -> AlphaTraderConnector:
    return AlphaTraderConnector(
        email=config["email"],
        password=config["password"],
        headless=config.get("headless", False),
    )

