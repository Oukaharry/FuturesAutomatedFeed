"""
blackarrow_connector.py — Playwright-based connector for BlackArrow (Nelogica) trading platform.

Protocol notes (reverse-engineered via live session):
  - Platform: https://web.blackarrowtrading.com/
  - Transport: WSS + proprietary Hades binary protocol
  - Order log format captured:
      CreateNewOrder | strTicker=NQFUT|nExchangeID=77|fPrice=<price>|nQty=<qty>
                     |nSide=buy|nOrderType=Market|dtValidity=<day> 16:00:00
  - Bracket (OCO) orders: OrderOCOStrategyHadesReceiver, ooType 0=entry 1=TP 2=SL
  - Bracket UI: Chart Trading Panel → <Custom> bracket dropdown → Gain (TP) + Loss (SL)
    in Ticks / Cash / Percent units
  - 2FA: 6-digit code emailed every new session — enter manually when prompted

USAGE:
    from connectors.blackarrow_connector import BlackArrowConnector
    conn = BlackArrowConnector(
        email="user@example.com",
        password="secret",
        account_id="2947168",    # numeric account ID shown on platform
    )
    conn.connect()
    conn.place_order("NQFUT", side="buy", qty=1, tp_ticks=50, sl_ticks=100)
    conn.close_all()
    conn.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
BLACKARROW_URL = "https://web.blackarrowtrading.com/"
DEFAULT_TIMEOUT_MS = 15_000       # Playwright timeout for most waits
CONFIRM_TIMEOUT_MS = 8_000        # Shorter timeout for confirmation dialogs
ORDER_SETTLE_S = 2.0              # Seconds to wait after placing an order


class BlackArrowConnector:
    """
    Controls the BlackArrow web trading platform via Playwright browser automation.

    All public methods are synchronous wrappers around async Playwright calls.
    The browser is launched (or re-used) lazily on the first call to `connect()`.

    Parameters
    ----------
    email : str
        BlackArrow account email address.
    password : str
        BlackArrow account password.
    account_id : str
        Numeric account ID shown in the platform (e.g. '2947168').
    headless : bool
        Run Chromium headless (default: False so the 2FA browser window stays visible).
    """

    def __init__(
        self,
        email: str,
        password: str,
        account_id: str = "",
        headless: bool = False,
    ):
        self.email = email
        self.password = password
        self.account_id = account_id
        self.headless = headless

        self._playwright = None
        self._browser = None
        self._page = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False

    # ================================================================== #
    # Public synchronous API
    # ================================================================== #

    def connect(self) -> bool:
        """Launch browser, log in to BlackArrow, handle 2FA. Returns True on success."""
        return self._run(self._async_connect())

    def disconnect(self):
        """Close the browser."""
        self._run(self._async_disconnect())

    def place_order(
        self,
        symbol: str,
        side: str,              # "buy" or "sell"
        qty: int = 1,
        tp_ticks: Optional[int] = None,
        sl_ticks: Optional[int] = None,
    ) -> bool:
        """
        Place a market order on `symbol`.

        If tp_ticks and sl_ticks are provided a bracket (OCO) order is placed
        using the Chart Trading Panel's <Custom> bracket widget.

        Parameters
        ----------
        symbol : str
            Ticker as shown on the platform (e.g. 'NQFUT').
        side : str
            'buy' or 'sell'.
        qty : int
            Number of contracts.
        tp_ticks : int | None
            Take-profit distance in ticks. If None, no TP is set.
        sl_ticks : int | None
            Stop-loss distance in ticks. If None, no SL is set.
        """
        return self._run(self._async_place_order(symbol, side, qty, tp_ticks, sl_ticks))

    def close_all(self, symbol: str = "NQFUT") -> bool:
        """Close all open positions via the 'Close Position' button (if visible)."""
        return self._run(self._async_close_all(symbol))

    def get_account_balance(self) -> Optional[float]:
        """Return the account balance shown in the platform header, or None."""
        return self._run(self._async_get_balance())

    def get_account_stats(self) -> dict:
        """Return a dict with Balance, MLL, SOD Balance and DailyPnL for pre-flight / SL sizing."""
        if self._page:
            try:
                return self._run(self._async_get_stats())
            except Exception as e:
                logger.warning("get_account_stats error: %s", e)
        bal = self.get_account_balance()
        return {"Balance": f"${bal:,.2f}" if bal is not None else "N/A"}

    def is_connected(self) -> bool:
        return self._connected

    # ================================================================== #
    # Async internals
    # ================================================================== #

    def _run(self, coro):
        """Run an async coroutine on the connector's event loop."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    # ------------------------------------------------------------------ #
    # Login / session management
    # ------------------------------------------------------------------ #

    async def _async_connect(self) -> bool:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        context = await self._browser.new_context()
        self._page = await context.new_page()

        logger.info("Navigating to BlackArrow…")
        await self._page.goto(BLACKARROW_URL, timeout=DEFAULT_TIMEOUT_MS)

        # Fill login form
        await self._page.fill('input[type="email"], input[name="email"], input[placeholder*="mail" i]', self.email)
        await self._page.fill('input[type="password"]', self.password)
        await self._page.click('button[type="submit"], button:has-text("Log in"), button:has-text("Login")')

        # Wait for 2FA dialog or main app
        try:
            await self._page.wait_for_selector(
                'input[placeholder*="code" i], input[maxlength="6"], [class*="otp" i], [class*="2fa" i]',
                timeout=10_000,
            )
            # 2FA required — prompt the user to type the code directly in the browser
            await self._get_2fa_code()
            logger.info(
                "BlackArrow: 2FA input detected. Waiting up to 120 s for the user "
                "to enter the code manually in the browser window…"
            )
            # Wait for the 2FA input to disappear (user submitted the code)
            try:
                await self._page.wait_for_selector(
                    'input[placeholder*="code" i], input[maxlength="6"], [class*="otp" i], [class*="2fa" i]',
                    state="hidden",
                    timeout=120_000,
                )
            except Exception:
                logger.warning("2FA input still visible after 120 s — proceeding anyway.")
        except Exception:
            logger.debug("No 2FA dialog detected — assuming direct login.")

        # Wait for the platform to be ready (price feed element)
        try:
            await self._page.wait_for_selector(
                '[class*="chart"], [class*="Chart"], canvas', timeout=30_000
            )
            self._connected = True
            logger.info("BlackArrow: logged in and platform ready.")
        except Exception as e:
            logger.error("BlackArrow: failed to reach platform after login: %s", e)
            self._connected = False

        return self._connected

    async def _get_2fa_code(self) -> Optional[str]:
        """Log a clear message asking the user to enter the 2FA code manually."""
        logger.warning(
            "BlackArrow 2FA required — check your email and enter the 6-digit code "
            "in the browser window. The browser is kept open for you to type it in."
        )
        print(
            "\n>>> BlackArrow 2FA: Please check your email and enter the 6-digit code "
            "in the browser window that opened. <<<\n"
        )
        # Return None — the caller will wait for the user to type the code directly
        # into the browser (headless=False so the window is visible).
        return None

    async def _async_disconnect(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._connected = False
        logger.info("BlackArrow: disconnected.")

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

        side_lower = side.lower()
        if side_lower not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")

        logger.info(
            "Placing %s %s qty=%d tp=%s sl=%s", side_lower, symbol, qty, tp_ticks, sl_ticks
        )

        use_bracket = tp_ticks is not None or sl_ticks is not None

        # ---- Set quantity in the Chart Trading qty spinner ----
        await self._set_qty(qty)

        # ---- Configure bracket if needed ----
        if use_bracket:
            await self._configure_bracket(
                tp_ticks=tp_ticks or 0,
                sl_ticks=sl_ticks or 0,
            )

        # ---- Click Buy/Sell at Market ----
        btn_text = "Buy at Mkt" if side_lower == "buy" else "Sell at Mkt"
        await page.click(f'button:has-text("{btn_text}")', timeout=DEFAULT_TIMEOUT_MS)

        # ---- Confirm dialog (if present) ----
        await self._confirm_order_dialog()

        await asyncio.sleep(ORDER_SETTLE_S)
        logger.info("Order placement complete.")
        return True

    async def _set_qty(self, qty: int):
        """Set the quantity in the Chart Trading Panel's quantity input."""
        page = self._page
        # The qty spinner is a number input next to the Buy/Sell buttons
        # Try direct fill first, then keyboard approach
        try:
            await page.evaluate(
                """(qty) => {
                    // Find all number-like inputs in the trading panel
                    const inputs = document.querySelectorAll('input[type="number"], input[class*="qty" i], input[class*="quantity" i]');
                    for (const inp of inputs) {
                        const rect = inp.getBoundingClientRect();
                        if (rect.width > 20 && rect.height > 10) {
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            nativeInputValueSetter.call(inp, qty);
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            break;
                        }
                    }
                }""",
                qty,
            )
        except Exception as e:
            logger.warning("_set_qty evaluate failed: %s", e)

    async def _configure_bracket(self, tp_ticks: int, sl_ticks: int):
        """
        Set the bracket TP and SL on the Chart Trading widget.

        BlackArrow bracket UI:
          - Dropdown at top of Chart Trading panel shows current bracket type
          - Click it → select "<Custom>" to enable Gain/Loss inputs
          - Gain = Take Profit (ticks), Loss = Stop Loss (ticks)
          - Units radio: Ticks / Cash / Percent — we always use Ticks
        """
        page = self._page

        # 1. Click the bracket dropdown to open it
        try:
            await page.click(
                '[class*="bracket" i] [class*="dropdown" i], [class*="bracketType" i]',
                timeout=5_000,
            )
            # Select <Custom>
            await page.click('text="<Custom>"', timeout=5_000)
        except Exception:
            logger.debug("Bracket dropdown click fallback — trying direct JS approach")
            # If dropdown is already on <Custom>, skip
            pass

        # 2. Ensure "Ticks" unit is selected
        await self._select_bracket_unit("Ticks")

        # 3. Set Gain (TP) and Loss (SL) values via JS (custom spinner components
        #    are not standard <input> elements interactable via Playwright's fill)
        await page.evaluate(
            """([gain, loss]) => {
                function setSpinner(element, value) {
                    // Try as native input
                    const nativeSet = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    )?.set;
                    if (nativeSet) {
                        nativeSet.call(element, value);
                        element.dispatchEvent(new Event('input', { bubbles: true }));
                        element.dispatchEvent(new Event('change', { bubbles: true }));
                        return;
                    }
                    // Contenteditable fallback
                    element.textContent = value;
                    element.dispatchEvent(new InputEvent('input', { bubbles: true, data: String(value) }));
                }

                // The bracket body contains two spinner inputs: [0]=Gain, [1]=Loss
                const bracketBody = document.querySelector(
                    '[class*="graphic-order__bracket" i], [class*="bracket-body" i], [class*="bracketBody" i]'
                );
                if (!bracketBody) return;

                const inputs = bracketBody.querySelectorAll('input');
                if (inputs[0]) setSpinner(inputs[0], gain);
                if (inputs[1]) setSpinner(inputs[1], loss);
            }""",
            [tp_ticks, sl_ticks],
        )
        logger.debug("Bracket configured: TP=%d ticks, SL=%d ticks", tp_ticks, sl_ticks)

    async def _select_bracket_unit(self, unit: str):
        """Select Ticks / Cash / Percent radio in the bracket widget."""
        page = self._page
        # Unit radios are labelled text nodes inside the bracket section
        try:
            await page.evaluate(
                """(unit) => {
                    const labels = document.querySelectorAll('[class*="bracket" i] label, [class*="graphic-order" i] label');
                    for (const lbl of labels) {
                        if (lbl.textContent.trim().toLowerCase() === unit.toLowerCase()) {
                            lbl.click();
                            return;
                        }
                    }
                    // Fallback: click radio input associated with matching text
                    const radios = document.querySelectorAll('[class*="bracket" i] input[type="radio"]');
                    const texts = document.querySelectorAll('[class*="bracket" i] [class*="label" i]');
                    for (let i = 0; i < texts.length; i++) {
                        if (texts[i].textContent.trim().toLowerCase() === unit.toLowerCase() && radios[i]) {
                            radios[i].click();
                            return;
                        }
                    }
                }""",
                unit,
            )
        except Exception as e:
            logger.debug("_select_bracket_unit error: %s", e)

    async def _confirm_order_dialog(self):
        """Click OK/Confirm on the order confirmation modal if it appears."""
        page = self._page
        try:
            # Wait briefly for the confirmation dialog
            ok_btn = await page.wait_for_selector(
                'button:has-text("OK"), button:has-text("Confirm"), button:has-text("Yes")',
                timeout=CONFIRM_TIMEOUT_MS,
            )
            if ok_btn:
                await ok_btn.click()
                logger.debug("Order confirmation dialog dismissed.")
        except Exception:
            logger.debug("No confirmation dialog appeared.")

    # ------------------------------------------------------------------ #
    # Position management
    # ------------------------------------------------------------------ #

    async def _async_close_all(self, symbol: str) -> bool:
        """
        Close all open positions for `symbol`.

        BlackArrow shows a 'Close Position' button in the open positions panel
        when a position is open. We click it and confirm.
        """
        page = self._page
        if page is None:
            logger.error("Not connected.")
            return False

        try:
            close_btn = await page.wait_for_selector(
                'button:has-text("Close Position"), button:has-text("Close All")',
                timeout=5_000,
            )
            if close_btn:
                await close_btn.click()
                await self._confirm_order_dialog()
                await asyncio.sleep(ORDER_SETTLE_S)
                logger.info("Close all positions sent for %s.", symbol)
                return True
        except Exception:
            logger.info("No open position close button found — nothing to close.")

        return False

    # ------------------------------------------------------------------ #
    # Account info
    # ------------------------------------------------------------------ #

    async def _async_get_balance(self) -> Optional[float]:
        """
        Scrape the account balance from the BlackArrow platform header.

        The header shows "$ X.XX" as a text node beside the account name
        (confirmed via live DOM inspection — Nelogica/Hades UI).

        Returns the numeric balance, or None if it can't be parsed.
        """
        page = self._page
        if page is None:
            return None
        try:
            # The header balance is a leaf element containing "$ X.XX" inside the
            # top navigation bar (sibling of the account selector dropdown).
            text = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('nav *');
                    for (const el of els) {
                        if (el.children.length === 0) {
                            const t = el.textContent.trim();
                            if (/^\\$ [\\d,]+\\.\\d{2}$/.test(t)) return t;
                        }
                    }
                    return null;
                }
            """)
            if text:
                num = re.sub(r"[^\d.]", "", text)
                return float(num) if num else None
        except Exception as e:
            logger.warning("get_balance error: %s", e)
        return None

    async def _async_get_stats(self) -> dict:
        """
        Scrape Balance, MLL (Max Loss Limit / drawdown floor), SOD Balance and
        daily P&L from the BlackArrow platform header.

        The platform header shows labelled stat cards similar to Alpha Trader:
          Balance / Equity / Daily P&L / MLL / SOD Balance

        Returns a dict with string values (dollar-formatted), keyed consistently
        with what trader_app.py expects for the full-cushion SL calculation:
          "Balance", "MLL", "SOD Balance", "DailyPnL"
        """
        page = self._page
        if page is None:
            return {}

        stats = {}

        async def _scrape_stat(label_text: str) -> Optional[str]:
            """
            Scrape a stat value from the BlackArrow trading panel.

            Confirmed DOM structure (Nelogica/Hades UI, live inspection):
              <div class="info">
                <span class="key">Daily PnL</span>
                <span class="value variation-down">$ -200.00</span>
              </div>

            For MLL / SOD Balance: only visible on funded challenge accounts,
            not on simulator accounts.  Label text may vary — we try several.
            """
            try:
                container = page.locator(f'.info:has(span.key:has-text("{label_text}")):has(span.value)')
                val_el = container.locator('span.value').first
                text = await val_el.inner_text(timeout=3_000)
                return text.strip() if text else None
            except Exception:
                pass
            return None

        # -- Header balance ("$ X.XX" leaf node in the top nav bar) ----------
        bal_text = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('nav *');
                for (const el of els) {
                    if (el.children.length === 0) {
                        const t = el.textContent.trim();
                        if (/^\\$ [\\d,]+\\.\\d{2}$/.test(t)) return t;
                    }
                }
                return null;
            }
        """)
        if bal_text:
            stats["Balance"] = bal_text

        # -- Trading panel stats (key/value pairs inside .info divs) ----------
        for label, key in (
            ("Daily PnL",    "DailyPnL"),
            ("Open PnL",     "OpenPnL"),
            ("Margin",       "Margin"),
            # Challenge-account-only stats — label text unconfirmed on sim;
            # try common Nelogica / The5ers naming conventions:
            ("MLL",          "MLL"),
            ("Max Loss",     "MLL"),
            ("Max Drawdown", "MLL"),
            ("DD Limit",     "MLL"),
            ("SOD Balance",  "SOD Balance"),
            ("Start Balance","SOD Balance"),
        ):
            val = await _scrape_stat(label)
            if val and key not in stats:
                stats[key] = val

        logger.debug("BlackArrow stats scraped: %s", stats)
        return stats


# ================================================================== #
# Convenience factory used by the trading engine
# ================================================================== #

def create_connector(config: dict) -> BlackArrowConnector:
    """
    Create a BlackArrowConnector from a config dict.

    Expected keys:
        email, password, account_id
    Optional:
        headless (bool)
    """
    return BlackArrowConnector(
        email=config["email"],
        password=config["password"],
        account_id=config.get("account_id", ""),
        headless=config.get("headless", False),
    )
