"""
alphatrader_connector.py — REST + Playwright connector for Alpha Futures' new platform.

Alpha Futures migrated from Tradovate to Alpha Trader (futures.alphatrader.com).

Protocol (reverse-engineered 2026-07-16):
  Auth:        POST https://apiv2.alphatrader.com/api/v1/auth/login/
               → Firebase JWT (id_token, refresh_token, expires_in=3600)
  T4 creds:    POST https://apiv2.alphatrader.com/api/v1/t4/credentials/token/
               → JWT with {t4_firm, t4_app_license, t4_username, t4_password}
  Orders:      wss://wss-sim.t4login.com/v1  (sim) / wss://wss.t4login.com/v1 (live)
               Binary protobuf — order placement via Playwright UI clicks
  Cancel-all:  POST https://apiv2.alphatrader.com/api/v1/t4/trading/cancel-all/
  Accounts:    GET  https://apiv2.alphatrader.com/api/v1/t4/accounts/
  Order hist:  GET  https://apiv2.alphatrader.com/api/v1/t4/orders/?account_id=<uuid>
  Trades:      GET  https://apiv2.alphatrader.com/api/v1/t4/trades/

Order schema (from order history GET):
  account_name, unique_id (UUID), market_id ("XCME_Eq ES (U26)"),
  exchange_id ("CME_Eq"), contract_id ("ES"), side ("buy"/"sell"),
  order_type ("market"/"limit"/"stop_market"), order_link ("none"/"auto_oco_p"),
  volume, filled_volume, price, limit_price, stop_price,
  is_bracket (bool), parent_order_id, status

Bracket orders (AutoOCO):
  - TP: limit order, order_link="auto_oco_p"
  - SL: stop_market order, order_link="auto_oco_p"
  - UI fields: spinbutton[0]=TP price, spinbutton[1]=SL price (absolute prices, not ticks)
  - To convert: tp_price = entry_price + (tp_ticks * tick_size)

USAGE:
    conn = AlphaTraderConnector(email="user@example.com", password="secret")
    conn.connect()
    conn.place_order("NQ", side="buy", qty=2, tp_ticks=202, sl_ticks=175)
    conn.close_all("NQ")
    conn.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import json
import base64
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
API_BASE = "https://apiv2.alphatrader.com/api/v1"
PLATFORM_URL = "https://futures.alphatrader.com/"
DEFAULT_TIMEOUT_MS = 15_000
CONFIRM_TIMEOUT_MS = 8_000
ORDER_SETTLE_S = 2.0
TOKEN_REFRESH_BUFFER_S = 300   # Refresh token 5 min before expiry

# Tradovate symbol → Alpha Trader contract_id
SYMBOL_MAP: dict[str, str] = {
    # NQ (E-mini Nasdaq-100)
    "NQ": "NQ", "NQU6": "NQ", "NQM6": "NQ", "NQH6": "NQ", "NQZ6": "NQ",
    "NQU5": "NQ", "NQM5": "NQ", "NQH5": "NQ", "NQZ5": "NQ",
    # MNQ (Micro E-mini Nasdaq-100)
    "MNQ": "MNQ", "MNQU6": "MNQ", "MNQM6": "MNQ", "MNQH6": "MNQ", "MNQZ6": "MNQ",
    "MNQU5": "MNQ", "MNQM5": "MNQ", "MNQH5": "MNQ", "MNQZ5": "MNQ",
    # ES (E-mini S&P 500)
    "ES": "ES", "ESU6": "ES", "ESM6": "ES", "ESH6": "ES", "ESZ6": "ES",
    # MES (Micro E-mini S&P 500)
    "MES": "MES", "MESU6": "MES", "MESM6": "MES",
    # GC (Gold)
    "GC": "GC", "GCM6": "GC", "GCQ6": "GC", "GCZ6": "GC",
    # MGC (Micro Gold)
    "MGC": "MGC", "MGCM6": "MGC", "MGCQ6": "MGC",
    # CL (Crude Oil)
    "CL": "CL", "CLM6": "CL", "CLN6": "CL",
}

# Tick size in index/commodity points per tick
TICK_SIZE: dict[str, float] = {
    "NQ": 0.25, "MNQ": 0.25,
    "ES": 0.25, "MES": 0.25,
    "GC": 0.10, "MGC": 0.10,
    "CL": 0.01,
}

# Exchange id per contract
EXCHANGE_MAP: dict[str, str] = {
    "NQ": "CME_Eq", "MNQ": "CME_Eq",
    "ES": "CME_Eq", "MES": "CME_Eq",
    "GC": "CME_CO", "MGC": "CME_CO",
    "CL": "NYMEX",
}


def _map_symbol(tradovate_symbol: str) -> str:
    """Map a Tradovate-style symbol (e.g. 'NQU6') to Alpha Trader contract_id ('NQ')."""
    s = tradovate_symbol.strip().upper()
    return SYMBOL_MAP.get(s, re.sub(r"[A-Z]\d+$", "", s) or s)


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload (no signature verification needed here)."""
    try:
        payload_b64 = token.split(".")[1]
        # Add padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


# ================================================================== #
# Main connector class
# ================================================================== #

class AlphaTraderConnector:
    """
    Connector for Alpha Futures' trading platform at futures.alphatrader.com.

    Uses the Alpha Trader REST API for auth/account management and Playwright
    browser automation for order placement (orders go to T4 WebSocket internally).

    Parameters
    ----------
    email : str
        Alpha Trader account email.
    password : str
        Alpha Trader account password.
    headless : bool
        Run Chromium headless. Default False (so you can watch orders execute).
    """

    def __init__(self, email: str, password: str, headless: bool = False):
        self.email = email
        self.password = password
        self.headless = headless

        # Auth state
        self._id_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_exp: float = 0.0          # Unix timestamp of expiry

        # Account state (populated after login)
        self._account_uuid: Optional[str] = None   # DA43F344-... (T4 UUID)
        self._account_name: Optional[str] = None   # ADVEV2026...

        # Playwright
        self._playwright = None
        self._browser = None
        self._page = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False

    # ================================================================== #
    # Public synchronous API
    # ================================================================== #

    def connect(self) -> bool:
        """Authenticate via REST API and launch the trading platform in a browser."""
        return self._run(self._async_connect())

    def disconnect(self):
        """Close the browser session."""
        self._run(self._async_disconnect())

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int = 1,
        tp_ticks: Optional[int] = None,
        sl_ticks: Optional[int] = None,
    ) -> bool:
        """
        Place a market order. If tp_ticks/sl_ticks are provided, an AutoOCO
        bracket order is placed with TP and SL as absolute limit/stop prices.

        Parameters
        ----------
        symbol : str
            Tradovate-style ticker ('NQU6', 'MNQU6') or Alpha Trader contract_id ('NQ').
        side : str
            'buy' or 'sell'.
        qty : int
            Number of contracts.
        tp_ticks : int | None
            Take-profit distance in ticks from fill price.
        sl_ticks : int | None
            Stop-loss distance in ticks from fill price.
        """
        return self._run(self._async_place_order(symbol, side, qty, tp_ticks, sl_ticks))

    def close_all(self, symbol: str = "NQ") -> bool:
        """Close all open positions for the given symbol via UI button."""
        return self._run(self._async_close_all(symbol))

    def flatten_all(self) -> bool:
        """
        Cancel all orders and close all positions via
        POST /api/v1/t4/trading/cancel-all/ REST endpoint.
        """
        return self._rest_cancel_all()

    def get_account_balance(self) -> Optional[float]:
        """Return the available balance from the REST accounts endpoint."""
        data = self._rest_get_accounts()
        if data:
            acct = next(
                (a for a in data if a.get("account_id") == self._account_uuid),
                data[0] if data else None,
            )
            if acct:
                return float(acct.get("available_balance", acct.get("balance", 0)))
        return None

    def get_account_info(self) -> Optional[dict]:
        """Return full account info dict from the REST API."""
        data = self._rest_get_accounts()
        if data:
            return next(
                (a for a in data if a.get("account_id") == self._account_uuid),
                data[0] if data else None,
            )
        return None

    def get_active_account(self) -> Optional[str]:
        """Return the active account name (e.g. 'ADVEV2026060800605').

        Tries in order:
          1. Cached ``_account_name`` set during login / REST fetch.
          2. DOM scrape of the account selector shown in the platform header.
        """
        if self._account_name:
            return self._account_name
        # Fallback: read from the browser DOM
        if self._page:
            try:
                name = self._run(self._async_read_account_name())
                if name:
                    self._account_name = name
                    return name
            except Exception as e:
                logger.warning("get_active_account DOM fallback failed: %s", e)
        return None

    def get_account_stats(self) -> dict:
        """Return a dict with Balance, Equity, DailyPnL keys for the UI pre-flight log."""
        if self._page:
            try:
                return self._run(self._async_get_stats())
            except Exception as e:
                logger.warning("get_account_stats error: %s", e)
        # REST fallback
        balance = self.get_account_balance()
        return {"Balance": f"${balance:,.2f}" if balance is not None else "N/A"}

    def is_connected(self) -> bool:
        return self._connected

    # ================================================================== #
    # REST API helpers (synchronous, no browser)
    # ================================================================== #

    def _ensure_token(self):
        """Re-login or refresh the Firebase JWT if it's expired or about to expire."""
        if self._id_token and time.time() < self._token_exp - TOKEN_REFRESH_BUFFER_S:
            return  # Token still valid

        if self._refresh_token:
            try:
                self._rest_refresh_token()
                return
            except Exception as e:
                logger.warning("Token refresh failed, re-logging in: %s", e)

        self._rest_login()

    def _rest_login(self):
        """POST /api/v1/auth/login/ and store tokens."""
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
        self._id_token = tokens["id_token"]
        self._refresh_token = tokens.get("refresh_token")
        expires_in = int(tokens.get("expires_in", 3600))
        self._token_exp = time.time() + expires_in
        logger.info("Alpha Trader: logged in as %s (token valid %ds)", self.email, expires_in)

    def _rest_refresh_token(self):
        """
        Refresh the Firebase ID token using the refresh_token grant.
        Firebase token refresh: POST https://securetoken.googleapis.com/v1/token
        """
        resp = requests.post(
            "https://securetoken.googleapis.com/v1/token",
            params={"key": "AIzaSyD-PLACEHOLDER"},   # API key embedded in JWT issuer
            json={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            self._id_token = data.get("id_token")
            expires_in = int(data.get("expires_in", 3600))
            self._token_exp = time.time() + expires_in
        else:
            # Fall back to full re-login
            self._rest_login()

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._id_token}",
            "Content-Type": "application/json",
        }

    def _rest_get_accounts(self) -> Optional[list]:
        try:
            resp = requests.get(f"{API_BASE}/t4/accounts/", headers=self._auth_headers(), timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.warning("get_accounts error: %s", e)
            return None

    def _rest_cancel_all(self) -> bool:
        try:
            resp = requests.post(
                f"{API_BASE}/t4/trading/cancel-all/",
                headers=self._auth_headers(),
                json={"account_id": self._account_uuid} if self._account_uuid else {},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Alpha Trader: cancel-all sent.")
            return True
        except Exception as e:
            logger.warning("cancel_all REST error: %s", e)
            return False

    # ================================================================== #
    # Async internals (Playwright)
    # ================================================================== #

    def _run(self, coro):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    async def _async_connect(self) -> bool:
        from playwright.async_api import async_playwright

        # Step 1: REST login (no browser needed)
        try:
            self._rest_login()
        except Exception as e:
            logger.error("Alpha Trader REST login failed: %s", e)
            return False

        # Step 2: Fetch account UUID
        accounts = self._rest_get_accounts()
        if accounts:
            default = next((a for a in accounts if a.get("is_default")), accounts[0])
            self._account_uuid = default.get("account_id")
            self._account_name = default.get("account_name")
            logger.info("Alpha Trader: using account %s (%s)", self._account_name, self._account_uuid)

        # Step 3: Launch browser and navigate to platform
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        context = await self._browser.new_context()
        self._page = await context.new_page()

        # Inject the Firebase auth token into localStorage so the app logs in automatically
        await self._page.goto(PLATFORM_URL, timeout=DEFAULT_TIMEOUT_MS)
        await self._page.wait_for_load_state("domcontentloaded")

        # Fill login form (the app redirects to /signin if not authenticated)
        if "/signin" in self._page.url:
            await self._page.fill('input[placeholder="Email"]', self.email)
            await self._page.fill('input[placeholder="Password"]', self.password)
            await self._page.click('button:has-text("Login")')

        # Wait for the platform to be ready (account balance in header)
        try:
            await self._page.wait_for_selector(
                'text="Current Balance"', timeout=DEFAULT_TIMEOUT_MS
            )
            self._connected = True
            logger.info("Alpha Trader: platform ready.")

            # Read account name from DOM if it wasn't set by the REST API
            if not self._account_name:
                self._account_name = await self._async_read_account_name()
                if self._account_name:
                    logger.info("Alpha Trader: account name from DOM = %s", self._account_name)

            # Make sure Order panel is visible
            await self._page.click('button:has-text("Order")')
            await self._page.wait_for_timeout(500)

        except Exception as e:
            logger.error("Alpha Trader: platform failed to load: %s", e)
            self._connected = False

        return self._connected

    async def _async_disconnect(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._connected = False
        logger.info("Alpha Trader: disconnected.")

    # ------------------------------------------------------------------ #
    # Order placement
    # ------------------------------------------------------------------ #

    async def _async_place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        tp_ticks: Optional[int],
        sl_ticks: Optional[int],
    ) -> bool:
        page = self._page
        if page is None:
            logger.error("Not connected.")
            return False

        contract_id = _map_symbol(symbol)
        tick_size = TICK_SIZE.get(contract_id, 0.25)
        side_lower = side.lower()
        use_bracket = (tp_ticks is not None) or (sl_ticks is not None)

        logger.info(
            "AlphaTrader: placing %s %s qty=%d tp=%s sl=%s",
            side_lower, contract_id, qty, tp_ticks, sl_ticks,
        )

        # ---- Switch to the correct contract ----
        await self._switch_contract(contract_id)

        # ---- Set quantity ----
        await self._set_qty(qty)

        # ---- Configure AutoOCO/bracket if needed ----
        if use_bracket:
            # Get current bid/ask from page to calculate absolute prices
            entry_est = await self._get_current_price(side_lower)
            if entry_est is None:
                logger.warning("Could not read current price; bracket may be inaccurate.")
                entry_est = 0.0

            tp_price: Optional[float] = None
            sl_price: Optional[float] = None

            if side_lower == "buy":
                if tp_ticks:
                    tp_price = entry_est + tp_ticks * tick_size
                if sl_ticks:
                    sl_price = entry_est - sl_ticks * tick_size
            else:  # sell
                if tp_ticks:
                    tp_price = entry_est - tp_ticks * tick_size
                if sl_ticks:
                    sl_price = entry_est + sl_ticks * tick_size

            # Round to tick size
            if tp_price is not None:
                tp_price = round(round(tp_price / tick_size) * tick_size, 4)
            if sl_price is not None:
                sl_price = round(round(sl_price / tick_size) * tick_size, 4)

            await self._configure_bracket(tp_price, sl_price)
        else:
            # Ensure bracket is disabled to place a plain market order
            await self._disable_bracket()

        # ---- Click BUY/SELL at Market ----
        btn_text = "BUY" if side_lower == "buy" else "SELL"
        await page.click(f'button:has-text("{btn_text}")', timeout=DEFAULT_TIMEOUT_MS)

        await asyncio.sleep(ORDER_SETTLE_S)
        logger.info("AlphaTrader: order placement complete.")
        return True

    # Full display name for each contract_id — used for the search filter
    _CONTRACT_DISPLAY: dict[str, str] = {
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

    async def _switch_contract(self, contract_id: str):
        """
        Switch the active contract in the Order panel.

        Uses the React-Select combobox: type the contract_id short code to filter,
        then click the matching option.  Skips if the contract is already selected.
        """
        page = self._page
        try:
            # Check current contract label
            current = await page.evaluate(
                """() => {
                    // The selected value appears in a div containing the contract name
                    const el = document.querySelector('[class*="singleValue"]');
                    return el ? el.textContent.trim() : '';
                }"""
            )
            target_display = self._CONTRACT_DISPLAY.get(contract_id, contract_id)
            if target_display.lower() in (current or "").lower():
                logger.debug("_switch_contract: already on %s", contract_id)
                return

            # Find the React-Select input for contracts
            # It's identifiable as the combobox that is *not* in a hidden/zero-size container
            combo_input = await page.evaluate(
                """() => {
                    const inputs = Array.from(document.querySelectorAll('input[role="combobox"]'));
                    // The contracts combobox is in the Order panel (visible, not the account one)
                    for (const inp of inputs) {
                        const rect = inp.getBoundingClientRect();
                        if (rect.height > 10) return inp.id;
                    }
                    // Fallback: return largest combobox id
                    return inputs.length > 0 ? inputs[inputs.length - 1].id : null;
                }"""
            )

            if not combo_input:
                logger.warning("_switch_contract: could not find combobox input")
                return

            # Focus the input, type the short code to filter options
            await page.click(f'#{combo_input}', timeout=5_000)
            await page.fill(f'#{combo_input}', contract_id)
            await page.wait_for_timeout(400)

            # Click the first (and usually only) matching option
            option_sel = f'[id*="option"]:has-text("{target_display}")'
            await page.click(option_sel, timeout=5_000)
            await page.wait_for_timeout(500)

            # Switch back to Order panel (selecting a contract opens the chart)
            await page.click('button:has-text("Order")', timeout=5_000)
            await page.wait_for_timeout(400)

            logger.info("_switch_contract: switched to %s (%s)", contract_id, target_display)

        except Exception as e:
            logger.warning("_switch_contract error: %s", e)

    async def _set_qty(self, qty: int):
        """Set the number of contracts in the Order panel."""
        page = self._page
        try:
            # Quick-select preset buttons first (1, 3, 5, 10, 15)
            presets = {1: "1", 3: "3", 5: "5", 10: "10", 15: "15"}
            if qty in presets:
                btns = page.locator(f'[class*="quantity" i] button:has-text("{presets[qty]}"), '
                                    f'button[class*="quick" i]:has-text("{presets[qty]}")')
                if await btns.count() > 0:
                    await btns.first.click()
                    return

            # Fall back to typing into the spinbutton
            spin = page.locator('[role="spinbutton"]').filter(has_text=re.compile(r"^\d+$")).first
            await spin.triple_click()
            await spin.type(str(qty))
        except Exception as e:
            logger.warning("_set_qty error: %s", e)

    async def _get_current_price(self, side: str) -> Optional[float]:
        """Read the current bid (for sells) or ask (for buys) from the Order panel."""
        page = self._page
        # Brief wait to ensure price feed has updated after a symbol switch
        await page.wait_for_timeout(300)
        try:
            label = "ask" if side == "buy" else "bid"
            price_text = await page.evaluate(
                f"""() => {{
                    const allText = document.body.innerText;
                    const match = allText.match(/{label}[:\\s]+([$\\d,]+\\.\\d+)/i);
                    return match ? match[1].replace(/[$,]/g, '') : null;
                }}"""
            )
            if price_text:
                return float(price_text)
        except Exception as e:
            logger.warning("_get_current_price error: %s", e)
        return None

    async def _configure_bracket(self, tp_price: Optional[float], sl_price: Optional[float]):
        """
        Enable the AutoOCO bracket and set TP/SL prices.

        The bracket section has two spinbutton[role] inputs:
          [0] = Take Profit price
          [1] = Stop Loss price
        """
        page = self._page

        # Expand the AutoOCO section if it's collapsed (no TP/SL number inputs visible)
        try:
            count = await page.locator('input[type="number"][placeholder="0.00"]').count()
            if count < 2:
                await page.click('text="AutoOCO/Bracket Order"', timeout=5_000)
                await page.wait_for_timeout(400)
        except Exception:
            pass

        try:
            # TP/SL fields are <input type="number" placeholder="0.00"> (NOT role=spinbutton).
            # Set via native value setter + React-compatible events.
            set_result = await page.evaluate(
                """([tp, sl]) => {
                    const inputs = Array.from(
                        document.querySelectorAll('input[type="number"][placeholder="0.00"]')
                    );
                    if (inputs.length < 2) return { ok: false, count: inputs.length };
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    function setVal(el, val) {
                        setter.call(el, String(val));
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
                    }
                    if (tp !== null) setVal(inputs[0], tp);
                    if (sl !== null) setVal(inputs[1], sl);
                    return { ok: true, tp: inputs[0].value, sl: inputs[1].value };
                }""",
                [tp_price, sl_price],
            )
            logger.debug("Bracket set result: %s", set_result)

        except Exception as e:
            logger.warning("_configure_bracket error: %s", e)

    async def _disable_bracket(self):
        """Collapse/disable the AutoOCO bracket section if it's expanded."""
        page = self._page
        try:
            # Bracket is open when the number inputs (TP/SL) are present
            count = await page.locator('input[type="number"][placeholder="0.00"]').count()
            if count > 0:
                await page.click('text="AutoOCO/Bracket Order"', timeout=3_000)
                await page.wait_for_timeout(300)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Position management
    # ------------------------------------------------------------------ #

    async def _async_close_all(self, symbol: str) -> bool:
        page = self._page
        if page is None:
            logger.error("Not connected.")
            return False

        contract_id = _map_symbol(symbol)
        await self._switch_contract(contract_id)

        try:
            # Try "CLOSE POSITION" button in the Order panel
            close_btn = page.locator('button:has-text("CLOSE POSITION")')
            if await close_btn.is_enabled(timeout=3_000):
                await close_btn.click()
                await asyncio.sleep(ORDER_SETTLE_S)
                logger.info("AlphaTrader: close_all sent for %s.", contract_id)
                return True
        except Exception:
            pass

        # Fallback: use REST cancel-all + FLATTEN ALL UI button
        try:
            flatten_btn = page.locator('button:has-text("FLATTEN ALL")')
            if await flatten_btn.is_enabled(timeout=3_000):
                await flatten_btn.click()
                await asyncio.sleep(ORDER_SETTLE_S)
                logger.info("AlphaTrader: flatten_all sent.")
                return True
        except Exception:
            pass

        logger.info("AlphaTrader: no open position to close for %s.", contract_id)
        return False

    async def _async_read_account_name(self) -> Optional[str]:
        """Read the selected account name from the DOM header selector."""
        page = self._page
        if page is None:
            return None
        import re as _re
        # Primary selector: the account wrapper div
        for sel in ('.accountSelectorWrapper', '[class*="singleValue"]'):
            try:
                el = page.locator(sel).first
                text = await el.inner_text(timeout=5_000)
                # Extract e.g. "ADVEV2026060800605" from "evaluation - ADVEV2026060800605"
                m = _re.search(r'[A-Z]{2,}[A-Z0-9]{10,}', text)
                if m:
                    return m.group(0)
                # If no match, return the full cleaned string
                return text.strip()
            except Exception:
                continue
        return None

    async def _async_get_stats(self) -> dict:
        """Scrape Balance, Equity and DailyPnL from the platform header."""
        page = self._page
        if page is None:
            return {}
        stats = {}

        async def _read_label(label: str) -> Optional[str]:
            try:
                # Header structure: <div>Label</div><div>Value</div> as siblings
                loc = page.locator(f'text="{label}"').first
                # The value is in the next sibling element
                val = await loc.evaluate(
                    'el => el.parentElement ? el.parentElement.children[1].innerText : ""',
                    timeout=4_000,
                )
                return (val or "").strip()
            except Exception:
                return None

        balance = await _read_label("Current Balance")
        if balance:
            stats["Balance"] = balance
        equity = await _read_label("Equity")
        if equity:
            stats["Equity"] = equity
        pnl = await _read_label("Net Daily PNL")
        if pnl:
            stats["DailyPnL"] = pnl
        mll = await _read_label("MLL")
        if mll:
            stats["MLL"] = mll
        sod = await _read_label("SOD Balance")
        if sod:
            stats["SOD Balance"] = sod

        return stats


# ================================================================== #
# Factory
# ================================================================== #

def create_connector(config: dict) -> AlphaTraderConnector:
    """
    Build an AlphaTraderConnector from a config dict.

    Expected keys: email, password
    Optional keys: headless (bool)
    """
    return AlphaTraderConnector(
        email=config["email"],
        password=config["password"],
        headless=config.get("headless", False),
    )
