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

CONTRACT_DISPLAY: dict[str, str] = {
    "NQ":  "E-mini NASDAQ-100",
    "MNQ": "E-mini Micro NASDAQ-100",
    "ES":  "E-mini S&P 500",
    "MES": "E-mini Micro S&P 500",
    "GC":  "Gold",
    "MGC": "E-micro Gold",
    "CL":  "Crude Oil",
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

            # Open the Order panel
            try:
                order_btns = self._driver.find_elements(By.XPATH, '//button[normalize-space()="Order"]')
                if order_btns:
                    order_btns[0].click()
                    time.sleep(0.5)
            except Exception:
                pass

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
        symbol:   str,
        side:     str,
        qty:      int            = 1,
        tp_ticks: Optional[int] = None,
        sl_ticks: Optional[int] = None,
    ) -> bool:
        if not self._driver or not self._connected:
            raise RuntimeError("AlphaTrader not connected — open the broker panel and click Connect first")

        contract_id = _map_symbol(symbol)
        tick_size   = TICK_SIZE.get(contract_id, 0.25)
        side_lower  = side.lower()
        use_bracket = (tp_ticks is not None) or (sl_ticks is not None)

        logger.info("AlphaTrader: placing %s %s qty=%d tp=%s sl=%s",
                    side_lower, contract_id, qty, tp_ticks, sl_ticks)

        self._switch_contract(contract_id)
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
            btns = self._driver.find_elements(
                By.XPATH,
                f'//button[contains(translate(normalize-space(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"{kw}") '
                f'and contains(translate(normalize-space(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"MARKET")]'
            )
            if not btns:
                # Fallback: exact match (some UI versions just show "BUY" / "SELL")
                btns = self._driver.find_elements(By.XPATH, f'//button[normalize-space()="{kw}"]')
            if btns:
                btns[0].click()
            else:
                raise RuntimeError(f"AlphaTrader: no '{kw} @ MARKET' button found — is the Order panel open?")
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

    def get_active_account(self) -> Optional[str]:
        if self._account_name:
            return self._account_name
        if self._driver:
            self._account_name = self._read_account_name()
        return self._account_name

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

    def _switch_contract(self, contract_id: str):
        driver = self._driver
        target = CONTRACT_DISPLAY.get(contract_id, contract_id)
        try:
            # Already on this contract?
            cur_els = driver.find_elements(By.CSS_SELECTOR, '[class*="singleValue"]')
            if cur_els and target.lower() in cur_els[0].text.lower():
                return

            # Find the React-Select combobox
            combos = driver.find_elements(By.CSS_SELECTOR, 'input[role="combobox"]')
            combo = next((c for c in combos if c.size.get("height", 0) > 10), None)
            if combo is None and combos:
                combo = combos[-1]
            if combo is None:
                return

            combo.click()
            combo.send_keys(Keys.CONTROL + "a")
            combo.send_keys(contract_id)
            time.sleep(0.4)

            opts = driver.find_elements(
                By.XPATH, f'//*[contains(@id,"option") and contains(normalize-space(),"{target}")]')
            if opts:
                opts[0].click()
            else:
                combo.send_keys(Keys.RETURN)
            time.sleep(0.5)

            # Return to Order panel
            ob = driver.find_elements(By.XPATH, '//button[normalize-space()="Order"]')
            if ob:
                ob[0].click()
            time.sleep(0.4)
        except Exception as e:
            logger.warning("_switch_contract: %s", e)

    def _set_qty(self, qty: int):
        driver = self._driver
        try:
            presets = {1: "1", 3: "3", 5: "5", 10: "10", 15: "15"}
            if qty in presets:
                for btn in driver.find_elements(By.XPATH, f'//button[normalize-space()="{presets[qty]}"]'):
                    if btn.is_displayed() and btn.is_enabled():
                        btn.click()
                        return
            spins = driver.find_elements(By.CSS_SELECTOR, '[role="spinbutton"]')
            if spins:
                spins[0].click()
                spins[0].send_keys(Keys.CONTROL + "a")
                spins[0].send_keys(str(qty))
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
            inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="number"][placeholder="0.00"]')
            if len(inputs) < 2:
                btns = driver.find_elements(By.XPATH, '//*[contains(text(),"AutoOCO/Bracket Order")]')
                if btns:
                    btns[0].click()
                    time.sleep(0.4)
            driver.execute_script("""
                const tp=arguments[0], sl=arguments[1];
                const inputs=[...document.querySelectorAll('input[type="number"][placeholder="0.00"]')];
                if(inputs.length<2) return;
                const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
                function sv(el,v){setter.call(el,String(v));
                  el.dispatchEvent(new Event('input',{bubbles:true}));
                  el.dispatchEvent(new Event('change',{bubbles:true}));
                  el.dispatchEvent(new FocusEvent('blur',{bubbles:true}));}
                if(tp!==null) sv(inputs[0],tp);
                if(sl!==null) sv(inputs[1],sl);
            """, tp, sl)
        except Exception as e:
            logger.warning("_configure_bracket: %s", e)

    def _disable_bracket(self):
        driver = self._driver
        try:
            if driver.find_elements(By.CSS_SELECTOR, 'input[type="number"][placeholder="0.00"]'):
                btns = driver.find_elements(By.XPATH, '//*[contains(text(),"AutoOCO/Bracket Order")]')
                if btns:
                    btns[0].click()
                    time.sleep(0.3)
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
            ("Balance",     "Current Balance"),
            ("Equity",      "Equity"),
            ("DailyPnL",    "Net Daily PNL"),
            ("MLL",         "MLL"),
            ("SOD Balance", "SOD Balance"),
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


# ================================================================== #
# Factory
# ================================================================== #

def create_connector(config: dict) -> AlphaTraderConnector:
    return AlphaTraderConnector(
        email=config["email"],
        password=config["password"],
        headless=config.get("headless", False),
    )

