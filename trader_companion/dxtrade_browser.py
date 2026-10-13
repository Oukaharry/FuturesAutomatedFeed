"""DXtrade web-terminal session driven through Chrome — the Tradovate pattern.

Mirrors ``TradovateAccount``: launch a persistent per-login Chrome profile,
open the broker's DXtrade login page, fill ``#username`` / ``#password`` and
submit, then keep the terminal tab open for keepalive and so the trader can
watch. 2FA (``#securityCode``) is left for the human to type when prompted.

Order placement and balance reads do NOT go through the UI — they use the
official DXtrade SCA REST API via ``DXTradeClient`` with the same
credentials (token auth). The browser gives visibility + web session; the
REST client gives deterministic trading. That split is exactly how the
Tradovate connector works (UI login, API token for orders).

Credentials come from the environment:
    DXTRADE_USERNAME, DXTRADE_PASSWORD           (required)
    DXTRADE_HOST   (default dx.tradeify247.co)
    DXTRADE_DOMAIN (default "default")
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from trader_companion.dxtrade_connector import (
    DXTradeClient, DXTradeError, DEFAULT_DOMAIN, TRADEIFY247_HOST,
)

logger = logging.getLogger("TradeOpssAI.dxtrade")


def credentials_from_env() -> dict:
    """Read DXtrade login details from the environment (.env is loaded by the app)."""
    return {
        "host": os.getenv("DXTRADE_HOST", TRADEIFY247_HOST).strip() or TRADEIFY247_HOST,
        "domain": os.getenv("DXTRADE_DOMAIN", DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN,
        "username": os.getenv("DXTRADE_USERNAME", "").strip(),
        "password": os.getenv("DXTRADE_PASSWORD", ""),
    }


class DXTradeBrowserSession:
    """One Chrome window per DXtrade login, plus a REST client for trading."""

    _chrome_instances: dict = {}
    _instance_locks: dict = {}
    _registry_guard = threading.Lock()

    # Any of these means the trading workspace has rendered (post-login).
    _WORKSPACE_READY_CSS = (
        "[data-test-id='work_area_header_top']",
        "[data-test-id='account_selector']",
        "[data-test-id='nav_POSITIONS']",
        "[data-test-id='one_click_trading']",
    )
    LOGIN_TIMEOUT_SEC = 180  # generous: human may need to type a 2FA code

    def __init__(self, username: str, password: str, *, host: str = TRADEIFY247_HOST,
                 domain: str = DEFAULT_DOMAIN, pair_id: str = None):
        if not username or not password:
            raise ValueError("DXtrade username/password required "
                             "(set DXTRADE_USERNAME / DXTRADE_PASSWORD in .env)")
        self.username = username
        self.password = password
        self.host = host.replace("https://", "").replace("http://", "").strip("/")
        self.domain = domain or DEFAULT_DOMAIN
        self.pair_id = pair_id or "default"
        self.login_url = f"https://{self.host}/"
        self.logged_in = False
        self.driver = None
        self.api = DXTradeClient(self.host, username, password, domain=self.domain)
        self.instance_key = f"dxtrade_{self.host}_{username}_{self.pair_id}"

        with DXTradeBrowserSession._registry_guard:
            self.lock = DXTradeBrowserSession._instance_locks.setdefault(
                self.instance_key, threading.RLock())
            existing = DXTradeBrowserSession._chrome_instances.get(self.instance_key)
            if existing is not None:
                try:
                    existing.current_url  # liveness probe
                    self.driver = existing
                    logger.info("Reusing Chrome for DXtrade %s", username)
                    return
                except Exception:
                    DXTradeBrowserSession._chrome_instances.pop(self.instance_key, None)
            self.driver = self._initialize_driver()
            DXTradeBrowserSession._chrome_instances[self.instance_key] = self.driver

    @classmethod
    def from_env(cls, **overrides) -> "DXTradeBrowserSession":
        creds = credentials_from_env()
        creds.update({k: v for k, v in overrides.items() if v is not None})
        return cls(creds["username"], creds["password"],
                   host=creds["host"], domain=creds["domain"],
                   pair_id=overrides.get("pair_id"))

    # ── Chrome ───────────────────────────────────────────────────────────

    @staticmethod
    def _cached_chromedriver_path():
        try:
            from trader_companion.tradovate import TradovateAccount
            return TradovateAccount._cached_chromedriver_path()
        except Exception:
            return None

    def _initialize_driver(self):
        opts = Options()
        safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", self.instance_key)
        profile_dir = os.path.join(tempfile.gettempdir(), "dxtrade_profiles", safe_key)
        os.makedirs(profile_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={profile_dir}")
        for arg in (
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-crash-reporter",
            "--disable-in-process-stack-traces", "--disable-logging", "--log-level=3",
            "--disable-features=TranslateUI", "--disable-component-update",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding", "--disable-extensions",
            "--disable-default-apps", "--disable-sync", "--window-size=1200,800",
            "--disable-blink-features=AutomationControlled",
        ):
            opts.add_argument(arg)
        opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_experimental_option("prefs", {
            "profile.default_content_setting_values": {
                "popups": 2, "notifications": 2, "images": 1},
        })
        cached = self._cached_chromedriver_path()
        logger.info("[CHROME] Launching DXtrade Chrome (profile=%s)", profile_dir)
        if cached:
            driver = webdriver.Chrome(service=Service(executable_path=cached), options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(45)
        driver.implicitly_wait(2)
        return driver

    # ── Login ────────────────────────────────────────────────────────────

    def _workspace_ready(self) -> bool:
        for css in self._WORKSPACE_READY_CSS:
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, css):
                    return True
            except Exception:
                continue
        return False

    def _on_login_page(self) -> bool:
        try:
            return bool(self.driver.find_elements(By.ID, "username"))
        except Exception:
            return False

    def _login_error_text(self) -> str:
        try:
            el = self.driver.find_element(By.ID, "login_error")
            return (el.text or "").strip() if el.is_displayed() else ""
        except Exception:
            return ""

    def login(self, api_login: bool = True) -> bool:
        """Open the terminal, auto-fill credentials, wait for the workspace.

        Returns True once the trading workspace has rendered. Also obtains the
        REST session token (api_login) so orders can be placed immediately.
        """
        with self.lock:
            self.driver.get(self.login_url)
            try:
                WebDriverWait(self.driver, 20).until(
                    lambda d: self._workspace_ready() or self._on_login_page())
            except Exception:
                logger.warning("DXtrade page did not render a login form or workspace")

            if self._on_login_page():
                self._fill_and_submit()

            deadline = time.time() + self.LOGIN_TIMEOUT_SEC
            prompted_2fa = False
            while time.time() < deadline:
                if self._workspace_ready():
                    break
                err = self._login_error_text()
                if err:
                    raise RuntimeError(f"DXtrade login rejected: {err}")
                if not prompted_2fa and self._needs_security_code():
                    prompted_2fa = True
                    logger.warning("DXtrade is asking for a 2FA security code — "
                                   "type it in the Chrome window")
                time.sleep(1.0)
            else:
                raise TimeoutError("DXtrade workspace did not load in time")

            self.logged_in = True
            logger.info("DXtrade web terminal ready for %s", self.username)

            if api_login:
                try:
                    self.api.login()
                    logger.info("DXtrade REST session established (timeout=%s)",
                                self.api.token_timeout)
                except DXTradeError as exc:
                    # UI is in; REST can be retried on first trade.
                    logger.warning("DXtrade REST login failed (UI is up): %s", exc)
            return True

    def _fill_and_submit(self):
        user = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "username")))
        pw = self.driver.find_element(By.ID, "password")
        user.clear()
        user.send_keys(self.username)
        pw.clear()
        pw.send_keys(self.password)
        try:
            self.driver.find_element(By.ID, "submitLogin").click()
        except Exception:
            pw.submit()

    def _needs_security_code(self) -> bool:
        try:
            el = self.driver.find_element(By.ID, "securityCode")
            return el.is_displayed()
        except Exception:
            return False

    # ── Price from the terminal DOM ──────────────────────────────────────
    # Tradeify247 does not grant the market-data API to client accounts
    # (errorCode 34), so the live price is read from the Market Depth widget
    # the terminal already renders. Rows are "bidQty | bidPrice | askPrice | askQty";
    # the first row is top of book.

    _QUOTE_JS = r"""
      const sym = arguments[0];
      const txt = e => (e.innerText || e.textContent || '').trim();
      const inp = document.querySelector("[data-test-id='market_depth_suggest']");
      const shown = inp ? inp.value : '';
      // Scope to the Market Depth widget: it is the ancestor that contains both
      // the symbol input and the bid/ask price column headers. Rows elsewhere
      // (e.g. the Positions table) must never be mistaken for the book.
      let scope = null;
      if (inp) {
        let el = inp;
        while (el && el !== document.body) {
          if (el.querySelector("[data-test-id='table_column_bid_price']") &&
              el.querySelector("[data-test-id='table_column_ask_price']")) { scope = el; break; }
          el = el.parentElement;
        }
      }
      if (!scope) return {symbolShown: shown, bid: null, ask: null, raw: null, scoped: false};
      const rows = Array.from(scope.querySelectorAll("[data-test-id='table_row']"));
      const nums = s => (s.match(/\d{1,3}(?:,\d{3})*(?:\.\d+)?/g) || [])
                        .map(x => parseFloat(x.replace(/,/g, '')));
      // Book row text: "bidAccum bidQty | bidPrice | askPrice askQty askAccum".
      // Prices are the two values flanking the middle separator; take the two
      // largest numbers (prices dwarf quantities for index/crypto perps).
      for (const r of rows) {
        const n = nums(txt(r));
        if (n.length < 2) continue;
        const sorted = [...n].sort((a,b)=>b-a);
        const p1 = sorted[0], p2 = sorted[1];
        if (p2 > 100 && p1 / p2 < 1.05) {   // two near-equal large numbers = bid/ask
          const bid = Math.min(p1,p2), ask = Math.max(p1,p2);
          return {symbolShown: shown, bid, ask, raw: txt(r), scoped: true};
        }
      }
      return {symbolShown: shown, bid: null, ask: null, raw: rows[0] ? txt(rows[0]) : null, scoped: true};
    """

    def get_quote_from_terminal(self, symbol: str = "BTC/USD", retries: int = 3) -> dict:
        """Top-of-book {bid, ask, mid} scraped from the Market Depth widget."""
        last = {}
        for _ in range(retries):
            with self.lock:
                try:
                    q = self.driver.execute_script(self._QUOTE_JS, symbol) or {}
                except Exception:
                    q = {}
            last = q
            shown = str(q.get("symbolShown") or "")
            if q.get("bid") and q.get("ask") and (not shown or shown == symbol):
                bid, ask = float(q["bid"]), float(q["ask"])
                return {"symbol": symbol, "bid": bid, "ask": ask,
                        "mid": round((bid + ask) / 2, 2), "raw": q.get("raw")}
            time.sleep(0.5)
        raise RuntimeError(f"No {symbol} quote visible in terminal (saw {last})")

    def set_terminal_symbol(self, symbol: str, settle_sec: float = 3.0) -> str:
        """Point the Market Depth widget at `symbol`; returns the symbol it shows."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        with self.lock:
            inp = self.driver.find_element(By.CSS_SELECTOR, "[data-test-id='market_depth_suggest']")
            if (inp.get_attribute("value") or "") == symbol:
                return symbol
            inp.click()
            time.sleep(0.3)
            inp.send_keys(Keys.COMMAND, "a")
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(Keys.BACKSPACE)
            inp.send_keys(symbol)
            time.sleep(1.0)
            inp.send_keys(Keys.ENTER)
        time.sleep(settle_sec)
        with self.lock:
            inp = self.driver.find_element(By.CSS_SELECTOR, "[data-test-id='market_depth_suggest']")
            return inp.get_attribute("value") or ""

    def quote(self, symbol: str) -> dict:
        """Switch the depth widget to `symbol` if needed, then read top of book."""
        shown = self.set_terminal_symbol(symbol)
        if shown != symbol:
            raise RuntimeError(f"Terminal would not switch to {symbol} (shows {shown!r})")
        return self.get_quote_from_terminal(symbol)

    # ── Companion broker facade ─────────────────────────────────────────
    # The status/breach pipeline in trader_app.py calls these on every
    # connected broker object; they return the same shapes TradovateAccount
    # does so DXtrade accounts flow through auto-Fail/Pass unchanged.

    def _ensure_api(self) -> bool:
        if self.api.logged_in:
            return True
        try:
            self.api.login()
            return True
        except DXTradeError as exc:
            logger.warning("DXtrade REST login failed: %s", exc)
            return False

    def account_codes(self) -> list:
        if not self._ensure_api():
            return []
        try:
            return self.api.list_account_codes()
        except DXTradeError:
            return []

    def _code_for(self, account_hint) -> str | None:
        """Match a dashboard account number (e.g. '1S10K2166973') to a DXtrade code
        ('default:1S10K2166973'); accepts either form."""
        hint = str(account_hint or "").strip()
        if not hint:
            codes = self.account_codes()
            return codes[0] if len(codes) == 1 else None
        hl = hint.lower()
        for code in self.account_codes():
            cl = code.lower()
            if cl == hl or cl.split(":", 1)[-1] == hl or cl.endswith(hl) or hl.endswith(cl.split(":", 1)[-1]):
                return code
        return None

    def get_trade_history(self):
        """[{account_name, balance, balance_sod, daily_pnl:[{date,trades,net_pnl}], ...}]"""
        if not self._ensure_api():
            return None
        out = []
        today = datetime.now(timezone.utc).date().isoformat()
        for code in self.account_codes():
            try:
                m = self.api.get_metrics(code)
            except DXTradeError:
                continue
            bal = float(m.get("balance") or 0)
            sod = self._sod_balance(code, bal, today)
            daily = self._daily_pnl(code)
            out.append({
                "account_name": code.split(":", 1)[-1],
                "account_code": code,
                "account_id": code,
                "environment": "dxtrade",
                "balance": bal,
                "balance_sod": sod,
                "realized_pnl": float(m.get("realizedPnL") or 0) if m.get("realizedPnL") is not None else bal - sod,
                "open_pnl": float(m.get("openPnL") or 0) if m.get("openPnL") is not None else 0.0,
                "daily_pnl": daily,
                "fills": [],
            })
        return out

    def _sod_balance(self, code: str, balance: float, today: str) -> float:
        """Balance at start of (UTC) day — remembered the first time we see the day."""
        store = getattr(self, "_sod_store", None)
        if store is None:
            store = {}
            self._sod_store = store
        rec = store.get(code)
        if not rec or rec.get("date") != today:
            # Prefer realized P&L if the server reports it, else first observed balance.
            store[code] = {"date": today, "balance": balance}
            rec = store[code]
        return float(rec["balance"])

    def _daily_pnl(self, code: str) -> list:
        """Per-UTC-day realized P&L from filled closing orders in order history."""
        try:
            orders = self.api.list_order_history(code)
        except DXTradeError:
            return []
        days: dict = {}
        for o in orders or []:
            status = str(o.get("status") or "").upper()
            if status not in ("COMPLETED", "FILLED", "EXECUTED"):
                continue
            ts = str(o.get("transactionTime") or o.get("updateTime") or o.get("issueTime") or "")
            day = ts[:10] if len(ts) >= 10 else None
            if not day:
                continue
            pnl = None
            for key in ("realizedPnL", "realizedPnl", "pnl", "profitLoss"):
                if o.get(key) is not None:
                    try:
                        pnl = float(o[key])
                    except (TypeError, ValueError):
                        pnl = None
                    break
            d = days.setdefault(day, {"date": day, "trades": 0, "net_pnl": 0.0})
            if str(o.get("positionEffect") or "").upper() == "CLOSE" or pnl is not None:
                d["trades"] += 1
                if pnl is not None:
                    d["net_pnl"] += pnl
        return sorted(days.values(), key=lambda x: x["date"])

    def has_open_position_for_account(self, expected_account=None):
        """(is_open, label) — same contract as TradovateAccount."""
        code = self._code_for(expected_account)
        if not code or not self._ensure_api():
            return False, "unknown"
        try:
            pos = self.api.list_positions(code)
        except DXTradeError:
            return False, "error"
        if not pos:
            return False, "flat"
        p = pos[0]
        return True, f"{p.get('side')} {p.get('quantity')} {p.get('symbol')}"

    def get_min_equity(self, account_id=None, **_):
        """{net_liq, net_liq_sod, min_equity, drawdown_remaining, ...}.

        DXtrade exposes no broker-side liquidation floor via the SCA API, so
        min_equity is left None here; the firm blueprint (static drawdown /
        daily loss) supplies the floor, exactly as for API-first firms.
        """
        code = self._code_for(account_id)
        if not code or not self._ensure_api():
            return None
        try:
            m = self.api.get_metrics(code)
        except DXTradeError:
            return None
        bal = float(m.get("balance") or 0)
        eq = float(m.get("equity") or bal)
        today = datetime.now(timezone.utc).date().isoformat()
        sod = self._sod_balance(code, bal, today)
        return {
            "account_id": code, "net_liq": eq, "net_liq_sod": sod,
            "min_equity": None, "trailing_max_drawdown": None,
            "trailing_max_drawdown_limit": None, "trailing_mode": "STATIC",
            "drawdown_remaining": None, "available": float(m.get("availableBalance") or 0),
        }

    def get_account_stats(self):
        codes = self.account_codes()
        if not codes:
            return {}
        try:
            m = self.api.get_metrics(codes[0])
        except DXTradeError:
            return {}
        return {"Balance": f"${float(m.get('balance') or 0):,.2f}",
                "Equity": f"${float(m.get('equity') or 0):,.2f}",
                "Account": codes[0]}

    def get_active_account(self):
        codes = self.account_codes()
        return codes[0].split(":", 1)[-1] if codes else None

    # ── Keepalive / health (same contract the Tradovate keepalive uses) ──

    def is_alive(self) -> bool:
        try:
            self.driver.current_url
            return True
        except Exception:
            return False

    def keepalive(self) -> bool:
        """Light UI touch + REST ping so neither session expires."""
        ok = True
        with self.lock:
            try:
                self.driver.execute_script("return document.title")
            except Exception:
                ok = False
        try:
            if self.api.logged_in:
                self.api.ping()
        except DXTradeError:
            ok = False
        return ok

    def close(self):
        try:
            self.api.logout()
        except Exception:
            pass
        with DXTradeBrowserSession._registry_guard:
            DXTradeBrowserSession._chrome_instances.pop(self.instance_key, None)
        try:
            self.driver.quit()
        except Exception:
            pass
        self.logged_in = False
