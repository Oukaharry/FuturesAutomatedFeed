#!/usr/bin/env python3
"""
Prop Firm Dashboard Scrapers — CDP-based (no Selenium required)
Scrapes account data from Tradeify, Lucid Trading, TopStep, and MFFU dashboards
via Chrome DevTools Protocol connecting to an already-open Chrome debug port.

Each class follows the standard interface:
  - login()           → attach to existing Chrome tab, verify logged in
  - get_account_stats() → basic account info for GUI display
  - get_billing_history() → subscription/purchase history
  - get_payouts()     → payout history
  - get_all_accounts() → all accounts 
  - is_connected()    → bool
  - close() / disconnect()

Requires Chrome running with:
  --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="<path>"
"""

__version__ = "1.00"
__build__ = "20260610"

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.parse

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ── Shared Chrome instance for CDP scrapers ─────────────────────────
_chrome_process = None
_chrome_lock = threading.Lock()
CDP_DEBUG_PORT = 9222
CDP_USER_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data CDP")


def _find_chrome_exe():
    """Locate Chrome executable on Windows."""
    candidates = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env, "")
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for p in candidates:
        if os.path.isfile(p):
            return p
    # Fallback: check PATH
    found = shutil.which("chrome") or shutil.which("google-chrome")
    return found


def _is_chrome_debug_running(port=CDP_DEBUG_PORT):
    """Check if Chrome debug port is already responding."""
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=2)
        return True
    except Exception:
        return False


def ensure_chrome_debug(url=None, port=CDP_DEBUG_PORT):
    """
    Ensure a Chrome instance with remote debugging is running.
    If one is already running on the port, just open the URL as a new tab.
    If not, launch a new Chrome process with the debug port.
    Returns True if Chrome is available on the port.
    """
    global _chrome_process

    with _chrome_lock:
        # Already running?
        if _is_chrome_debug_running(port):
            if url:
                _open_tab_in_debug_chrome(url, port)
            return True

        # Launch new Chrome
        chrome_exe = _find_chrome_exe()
        if not chrome_exe:
            raise FileNotFoundError(
                "Chrome not found. Install Google Chrome or set it on PATH.")

        args = [
            chrome_exe,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={CDP_USER_DATA_DIR}",
        ]
        if url:
            args.append(url)

        _chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for debug port to be ready
        for _ in range(30):
            time.sleep(0.5)
            if _is_chrome_debug_running(port):
                # Chrome first-run may hijack the initial URL — open it as a tab too
                if url:
                    time.sleep(1)
                    _open_tab_in_debug_chrome(url, port)
                return True

        raise TimeoutError(
            f"Chrome launched but debug port {port} not responding after 15s")


def shutdown_debug_chrome_spawned():
    """
    Terminate Chrome started by ensure_chrome_debug in this process.
    No-op if we attached to an existing debug port (did not spawn a child).
    """
    global _chrome_process
    proc = None
    with _chrome_lock:
        proc = _chrome_process
        _chrome_process = None
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        logging.warning("shutdown_debug_chrome_spawned: %s", e)


def _open_tab_in_debug_chrome(url, port=CDP_DEBUG_PORT):
    """Open a new tab in the already-running debug Chrome via the /json/new endpoint.
    Skips if a tab with the same domain is already open."""
    try:
        # Check if a tab with this domain is already open
        from urllib.parse import urlparse
        target_domain = urlparse(url).netloc
        data = urllib.request.urlopen(
            f'http://127.0.0.1:{port}/json', timeout=5).read()
        tabs = json.loads(data)
        for t in tabs:
            if t.get('type') == 'page':
                tab_domain = urlparse(t.get('url', '')).netloc
                if tab_domain and target_domain and tab_domain == target_domain:
                    return  # Already open
    except Exception:
        pass

    try:
        encoded = urllib.parse.quote(url, safe=':/')
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/json/new?{encoded}',
            method='PUT'
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        try:
            urllib.request.urlopen(
                f'http://127.0.0.1:{port}/json/new?{url}', timeout=5)
        except Exception:
            pass


class CDPBase:
    """
    Base class for CDP-based prop firm scrapers.
    Connects to a Chrome tab via WebSocket and executes JS fetch() calls
    from the browser context to use the site's session cookies/tokens.
    """

    DOMAIN = ""        # Override in subclasses: e.g. "app-f.tradeify.co"
    FIRM_NAME = ""     # Override: e.g. "Tradeify"
    _msg_id = 0

    def __init__(self, debug_port=9222, pair_id="default"):
        self.debug_port = debug_port
        self.pair_id = pair_id
        self.ws = None
        self.tab_url = None
        self.logged_in = False
        self._login_timestamp = None
        self._cached_stats = None
        self._stats_last_fetch = 0
        self.lock = threading.RLock()
        self.logger = logging.getLogger(f"{self.FIRM_NAME}_{pair_id}")

    # ── CDP Connection ──

    def _find_tab(self):
        """Find the browser tab matching this firm's domain."""
        try:
            data = urllib.request.urlopen(
                f'http://127.0.0.1:{self.debug_port}/json', timeout=5
            ).read()
            tabs = json.loads(data)
            for t in tabs:
                if t.get('type') == 'page' and self.DOMAIN in t.get('url', ''):
                    return t
        except Exception as e:
            self.logger.error(f"[CDP] Failed to list tabs: {e}")
        return None

    def _connect_ws(self, tab):
        """Connect WebSocket to a specific tab."""
        ws_url = tab.get('webSocketDebuggerUrl')
        if not ws_url:
            raise ConnectionError(f"No webSocketDebuggerUrl for tab: {tab.get('url')}")
        # Activate the target first — Chrome requires this for CDP to respond
        target_id = tab.get('id', '')
        if target_id:
            try:
                urllib.request.urlopen(
                    f'http://127.0.0.1:{self.debug_port}/json/activate/{target_id}',
                    timeout=5
                )
            except Exception:
                pass  # Non-critical, continue anyway
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.tab_url = tab.get('url')
        self.logger.info(f"[CDP] Connected to {self.tab_url}")

    def _send(self, method, params=None, timeout=30):
        """Send a CDP command and return the result."""
        CDPBase._msg_id += 1
        msg_id = CDPBase._msg_id
        msg = {'id': msg_id, 'method': method}
        if params:
            msg['params'] = params
        self.ws.send(json.dumps(msg))
        # Read responses until we get our ID back, skipping CDP events
        deadline = time.time() + timeout
        old_timeout = self.ws.gettimeout()
        try:
            while time.time() < deadline:
                self.ws.settimeout(max(0.1, deadline - time.time()))
                try:
                    resp = json.loads(self.ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if resp.get('id') == msg_id:
                    return resp
                # Skip CDP events (no 'id' field)
        finally:
            self.ws.settimeout(old_timeout)
        raise TimeoutError(f"CDP response timeout for {method}")

    def _js(self, expression, await_promise=False, timeout=None):
        """Execute JavaScript in the page and return the result value."""
        params = {'expression': expression, 'returnByValue': True}
        if await_promise:
            params['awaitPromise'] = True
        resp = self._send('Runtime.evaluate', params, timeout=timeout or (30 if await_promise else 10))
        result = resp.get('result', {}).get('result', {})
        if result.get('subtype') == 'error':
            desc = result.get('description', 'JS error')
            raise RuntimeError(f"JS error: {desc}")
        return result.get('value')

    def _fetch_json(self, url, method='GET', body=None, extra_headers=None):
        """Execute a fetch() call from the browser context and parse JSON response."""
        headers = {'Content-Type': 'application/json'}
        if extra_headers:
            headers.update(extra_headers)

        if body and method == 'POST':
            js = f"""
                (async () => {{
                    const r = await fetch({json.dumps(url)}, {{
                        method: 'POST',
                        credentials: 'include',
                        headers: {json.dumps(headers)},
                        body: JSON.stringify({json.dumps(body)})
                    }});
                    const text = await r.text();
                    return JSON.stringify({{status: r.status, body: text}});
                }})()
            """
        else:
            fetch_opts = f"{{credentials: 'include', headers: {json.dumps(headers)}}}"
            js = f"""
                (async () => {{
                    const r = await fetch({json.dumps(url)}, {fetch_opts});
                    const text = await r.text();
                    return JSON.stringify({{status: r.status, body: text}});
                }})()
            """

        raw = self._js(js, await_promise=True)
        if not raw:
            return None
        result = json.loads(raw)
        status = result.get('status', 0)
        if status != 200:
            self.logger.warning(f"[FETCH] {method} {url} → HTTP {status}")
            return None
        try:
            return json.loads(result['body'])
        except (json.JSONDecodeError, KeyError):
            return result.get('body')

    def _fetch_json_bearer(self, url, token, method='GET', body=None):
        """Fetch with Bearer token auth."""
        return self._fetch_json(url, method=method, body=body,
                                extra_headers={'Authorization': f'Bearer {token}'})

    # ── Standard Interface ──

    def login(self, open_url=None):
        """
        Attach to an existing Chrome tab for this firm.
        If open_url is provided and no tab is found, launch/reuse Chrome debug
        and open the URL, then wait for the tab to appear.
        """
        if not WS_AVAILABLE:
            raise ImportError("websocket-client package required: pip install websocket-client")

        tab = self._find_tab()

        # If no tab found and we have a URL, launch Chrome and open the tab
        if not tab and open_url:
            ensure_chrome_debug(url=open_url, port=self.debug_port)
            # Wait for the tab to appear (user may need to finish loading)
            for _ in range(30):
                time.sleep(1)
                tab = self._find_tab()
                if tab:
                    break

        if not tab:
            raise ConnectionError(
                f"No {self.FIRM_NAME} tab found on port {self.debug_port}. "
                f"Open {self.DOMAIN} in Chrome with --remote-debugging-port={self.debug_port}")
        self._connect_ws(tab)
        self.logged_in = True
        self._login_timestamp = time.time()
        self.logger.info(f"[LOGIN] Attached to {self.FIRM_NAME} tab")
        return True

    def is_connected(self):
        """Check if the WebSocket connection is alive."""
        try:
            if not self.ws or not self.ws.connected:
                return False
            # Quick ping with short timeout
            self._send('Runtime.evaluate',
                       {'expression': '1+1', 'returnByValue': True},
                       timeout=5)
            return True
        except Exception:
            self.logged_in = False
            return False

    def disconnect(self):
        """Close the WebSocket (does NOT close the Chrome tab)."""
        self.logged_in = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def close(self):
        """Alias for disconnect."""
        self.disconnect()

    def get_account_stats(self):
        """Override in subclasses."""
        return {}

    def get_billing_history(self):
        """Override in subclasses."""
        return []

    def get_all_accounts(self):
        """Override in subclasses."""
        return []

    def get_payouts(self):
        """Override in subclasses."""
        return []


# ═══════════════════════════════════════════════════════════════════════
#  TRADEIFY
# ═══════════════════════════════════════════════════════════════════════
class TradeifyAccount(CDPBase):
    """
    Tradeify dashboard scraper — MUI React app at app-f.tradeify.co
    Auth: session cookies (credentials: include)
    """
    DOMAIN = "tradeify.co"
    FIRM_NAME = "Tradeify"
    BASE = "https://app-f.tradeify.co"

    def _get_profile(self):
        return self._fetch_json(f"{self.BASE}/api/auth/profile/")

    def _get_broker_credentials(self):
        return self._fetch_json(f"{self.BASE}/api/dashboard/broker-credentials")

    def _get_account_overview(self):
        return self._fetch_json(
            f"{self.BASE}/api/dashboard/account-overview?hide_blown_account=true&page=1&page_size=10")

    def get_account_stats(self):
        """Return account stats from Tradeify account-overview + broker credentials."""
        with self.lock:
            now = time.time()
            if now - self._stats_last_fetch < 2.0 and self._cached_stats:
                return self._cached_stats

            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Open Trades": "0",
                "Symbol": "",
                "Direction": "",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
            }

            try:
                # account-overview has balance, status, type — nested {success, data: {success, ..., data: [...]}}
                overview = self._get_account_overview()
                if overview and overview.get('success'):
                    outer = overview.get('data', {})
                    items = outer.get('data', []) if isinstance(outer, dict) else []
                    if isinstance(items, list) and items:
                        first = items[0]
                        stats["Account Number"] = first.get('broker_account_id', 'Unknown')
                        bal = first.get('account_balance')
                        if bal is not None:
                            try:
                                stats["Balance"] = f"${float(bal):,.2f}"
                            except (ValueError, TypeError):
                                pass
                        init_bal = first.get('initial_balance')
                        daily_loss = first.get('daily_loss_limit')
                        if daily_loss is not None:
                            try:
                                stats["Drawdown"] = f"${float(daily_loss):,.2f}"
                            except (ValueError, TypeError):
                                pass
                        profit_target = first.get('profit_target')
                        if profit_target is not None:
                            try:
                                stats["Profit Target"] = f"${float(profit_target):,.2f}"
                            except (ValueError, TypeError):
                                pass
                        stats["Phase"] = first.get('funded_status', first.get('account_type', 'N/A'))
                        stats["Status"] = first.get('account_status', 'N/A')

                # Fallback to broker creds for account name if overview didn't have it
                if stats["Account Number"] == "Unknown":
                    creds = self._get_broker_credentials()
                    if creds and isinstance(creds, dict):
                        outer = creds.get('data', creds)
                        items = outer.get('data', outer) if isinstance(outer, dict) else outer
                        if isinstance(items, list) and items:
                            stats["Account Number"] = items[0].get('name', 'Unknown')
                            if stats["Status"] == "N/A":
                                stats["Status"] = "Active"

            except Exception as e:
                self.logger.warning(f"[STATS] Error: {e}")

            self._cached_stats = stats
            self._stats_last_fetch = now
            return stats

    def get_billing_history(self):
        """Get order history as billing records with Tradovate account linking."""
        billing = []
        page = 1
        while True:
            result = self._fetch_json(
                f"{self.BASE}/api/dashboard/get-order-list?page={page}&page_size=100")
            if not result or not isinstance(result, dict):
                break
            items = result.get('data', [])
            if not isinstance(items, list) or not items:
                break
            for item in items:
                plan = item.get('plan', {}) or {}
                payment = item.get('payment', {}) or {}
                broker_acct = item.get('broker_account', {}) or {}
                status_raw = str(item.get('status', '')).lower()
                price = float(item.get('amount', payment.get('amount_paid', plan.get('price', 0))) or 0)
                acct_no = broker_acct.get('broker_account_id', broker_acct.get('account_id', ''))
                billing.append({
                    "sn": str(item.get("id", "")),
                    "account_no": acct_no or str(item.get("id", "")),
                    "login": acct_no,
                    "status": "APPROVED" if status_raw in ("completed", "active", "paid", "approved") else str(item.get("status", "")),
                    "date": str(item.get("created_at", ""))[:10],
                    "paid_amount": f"${price:.2f}",
                    "paid_amount_numeric": price,
                    "funding_package": f"{plan.get('plan_type', '')} {plan.get('account_type', '')}".strip(),
                    "order_type": item.get("order_type", ""),
                    "coupon_code": (item.get('coupon_data') or {}).get('code', ''),
                    "payment_method": payment.get("payment_method", ""),
                    "transaction_id": payment.get("transaction_id", ""),
                })
            meta = result.get('meta', {})
            if page >= meta.get('total_pages', 1):
                break
            page += 1
        return billing

    def get_account_mapping(self):
        """Map Tradeify broker_account_id -> Tradovate account info.

        Uses get-order-list (broker_account has tradovate account_id) and
        account-overview (has broker_account_id + account_id) to build
        a mapping keyed by broker_account_id.
        """
        mapping = {}
        # account-overview gives broker_account_id -> account_id
        overview = self._fetch_json(
            f"{self.BASE}/api/dashboard/account-overview?hide_blown_account=false&page=1&page_size=100")
        if overview and overview.get('success'):
            outer = overview.get('data', {})
            items = outer.get('data', []) if isinstance(outer, dict) else []
            for item in (items if isinstance(items, list) else []):
                bid = item.get('broker_account_id', '')
                if bid:
                    balance = item.get('account_balance')
                    initial = item.get('initial_balance')
                    profit_target = item.get('profit_target')
                    daily_loss = item.get('daily_loss_limit')
                    # min_equity = initial_balance - daily_loss_limit
                    min_equity = None
                    if initial is not None and daily_loss is not None:
                        try:
                            min_equity = float(initial) - float(daily_loss)
                        except (ValueError, TypeError):
                            pass
                    acct_status = item.get('account_status', '')
                    mapping[bid] = {
                        "tradovate_account_name": bid,
                        "tradovate_account_id": item.get('account_id'),
                        "account_type": item.get('account_type'),
                        "funded_status": item.get('funded_status'),
                        "account_status": acct_status,
                        "initial_balance": initial,
                        "balance": balance,
                        "starting_balance": initial,
                        "profit_target": profit_target,
                        "min_equity": min_equity,
                        "breached": str(acct_status).lower() in ("breached", "failed", "blown"),
                    }
                    self.logger.info(
                        f"[MAPPING] broker={bid} account_id={item.get('account_id')} "
                        f"type={item.get('account_type')} target={profit_target} min_eq={min_equity}")
        self.logger.info(f"[MAPPING] Built mapping for {len(mapping)} account(s)")
        return mapping

    def get_all_accounts(self):
        """Get all accounts from account-overview endpoint."""
        overview = self._get_account_overview()
        if not overview or not overview.get('success'):
            return []
        outer = overview.get('data', {})
        items = outer.get('data', []) if isinstance(outer, dict) else []
        return items if isinstance(items, list) else []

    def get_payouts(self):
        """Get payout tracking data."""
        result = self._fetch_json(
            f"{self.BASE}/api/payouts/payout-tracking?page=1&page_size=100"
            f"&start_date=2020-01-01&end_date=2030-12-31"
        )
        if not result or not result.get('success'):
            return []
        # {success, data: {success, ..., data: [...]}}
        outer = result.get('data', {})
        items = outer.get('data', []) if isinstance(outer, dict) else []
        return items if isinstance(items, list) else []


# ═══════════════════════════════════════════════════════════════════════
#  LUCID TRADING
# ═══════════════════════════════════════════════════════════════════════
class LucidTradingAccount(CDPBase):
    """
    Lucid Trading dashboard scraper — Angular 19 app at dash.lucidtrading.com
    Auth: Bearer JWT from localStorage('auth_token') + cookies.
    API base: https://dash.lucidtrading.com/api
    Key: localStorage('userKey')
    """
    DOMAIN = "lucidtrading.com"
    FIRM_NAME = "Lucid Trading"
    BASE = "https://dash.lucidtrading.com"

    def _get_token(self):
        """Get JWT from localStorage."""
        return self._js("localStorage.getItem('auth_token')")

    def _get_user_key(self):
        """Get userKey from localStorage."""
        return self._js("localStorage.getItem('userKey')")

    def _fetch_lucid(self, url):
        """Fetch from Lucid API with Bearer token."""
        token = self._get_token()
        if token:
            return self._fetch_json_bearer(url, token)
        return self._fetch_json(url)

    def get_account_stats(self):
        """Get account stats from Lucid Trading."""
        with self.lock:
            now = time.time()
            if now - self._stats_last_fetch < 2.0 and self._cached_stats:
                return self._cached_stats

            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Open Trades": "0",
                "Symbol": "",
                "Direction": "",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
            }

            try:
                user_key = self._get_user_key()
                if not user_key:
                    return stats

                # /api/users/summary/{userKey} returns array of accounts
                summary = self._fetch_lucid(
                    f"{self.BASE}/api/users/summary/{user_key}")
                if isinstance(summary, list) and summary:
                    first = summary[0]
                    stats["Account Number"] = first.get('accountName', 'Unknown')
                    stats["Status"] = first.get('status', 'N/A')
                    stats["Phase"] = first.get('planCode', first.get('accountType', 'N/A'))
                    bal = first.get('accountBalance')
                    if isinstance(bal, (int, float)):
                        stats["Balance"] = f"${bal:,.2f}"
                    mll = first.get('minAccountBalance')
                    if isinstance(mll, (int, float)):
                        stats["Drawdown"] = f"${mll:,.2f}"
                    target = first.get('profitTarget')
                    if isinstance(target, (int, float)):
                        stats["Profit Target"] = f"${target:,.2f}"
                    pnl = first.get('totalPnlPeriod')
                    if isinstance(pnl, (int, float)):
                        stats["Profit/Loss"] = f"${pnl:,.2f}"

                # Get profile info
                profile = self._fetch_lucid(
                    f"{self.BASE}/api/users/wp-profile?userKey={user_key}")
                if isinstance(profile, dict):
                    name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
                    if name:
                        stats["Account Number"] = f"{stats['Account Number']} ({name})"

            except Exception as e:
                self.logger.warning(f"[STATS] Error: {e}")

            self._cached_stats = stats
            self._stats_last_fetch = now
            return stats

    def get_billing_history(self):
        """Get order history from Lucid's profile/order-history API with account linking."""
        user_key = self._get_user_key()
        if not user_key:
            return []
        orders = self._fetch_lucid(
            f"{self.BASE}/api/users/order-history?userKey={user_key}&limit=50&offset=0")
        if not isinstance(orders, list):
            return []

        # Build plan label -> accountName mapping for linking orders to accounts
        acct_by_plan = {}
        summary = self._fetch_lucid(f"{self.BASE}/api/users/summary/{user_key}")
        if isinstance(summary, list):
            for s in summary:
                label = (s.get('planLabel') or '').strip()
                name = s.get('accountName', '')
                if label and name:
                    acct_by_plan[label] = name

        billing = []
        for item in orders:
            amount = float(item.get("totalAmount", 0) or 0)
            status_raw = str(item.get("status", "")).lower()
            product = item.get("productNames", "")
            # Resolve account name: match productNames against planLabel
            # e.g. "LucidFlex 50K NT_TDV" matches planLabel "LucidFlex 50K"
            matched_acct = ""
            for label, acct_name in acct_by_plan.items():
                if label in product or product in label:
                    matched_acct = acct_name
                    break
            billing.append({
                "sn": str(item.get("orderId", "")),
                "account_no": matched_acct or str(item.get("orderId", "")),
                "login": matched_acct,
                "status": "APPROVED" if status_raw in ("completed", "active", "paid", "approved") else str(item.get("status", "")),
                "date": str(item.get("dateCreated", ""))[:10],
                "paid_amount": f"${amount:.2f}",
                "paid_amount_numeric": amount,
                "funding_package": product,
                "payment_method": item.get("paymentMethodTitle", ""),
                "transaction_id": item.get("transactionId", ""),
            })
        return billing

    def get_account_mapping(self):
        """Map Lucid account names to summary info for billing linking."""
        user_key = self._get_user_key()
        if not user_key:
            return {}
        summary = self._fetch_lucid(f"{self.BASE}/api/users/summary/{user_key}")
        if not isinstance(summary, list):
            return {}
        mapping = {}
        for s in summary:
            name = s.get('accountName', '')
            if name:
                balance = s.get('accountBalance')
                min_equity = s.get('minAccountBalance')  # minimum account balance before breach
                profit_target = s.get('profitTarget')     # target to pass
                status_raw = s.get('status', '')
                mapping[name] = {
                    "tradovate_account_name": name,
                    "plan_title": s.get('planLabel', s.get('planCode', '')),
                    "balance": balance,
                    "starting_balance": None,
                    "status": status_raw,
                    "profit_target": profit_target,
                    "min_equity": min_equity,
                    "breached": str(status_raw).lower() in ("breached", "failed", "blown"),
                }
                self.logger.info(f"[MAPPING] account={name} plan={s.get('planLabel')} "
                                 f"target={profit_target} min_eq={min_equity}")
        self.logger.info(f"[MAPPING] Built mapping for {len(mapping)} account(s)")
        return mapping

    def get_all_accounts(self):
        """Get all accounts from summary endpoint."""
        user_key = self._get_user_key()
        if not user_key:
            return []
        summary = self._fetch_lucid(
            f"{self.BASE}/api/users/summary/{user_key}")
        return summary if isinstance(summary, list) else []

    def get_payouts(self):
        """Get payout history."""
        user_key = self._get_user_key()
        if not user_key:
            return []
        result = self._fetch_lucid(
            f"{self.BASE}/api/payout/payout-history?userKey={user_key}")
        if not result:
            return []
        return result if isinstance(result, list) else result.get('data', [])


# ═══════════════════════════════════════════════════════════════════════
#  TOPSTEP
# ═══════════════════════════════════════════════════════════════════════
class TopStepAccount(CDPBase):
    """
    TopStep dashboard scraper — React + Apollo GraphQL at dashboard.topstep.com
    Auth: httpOnly session cookies (credentials: include)
    REST base: https://api.topstep.com
    GraphQL: https://crystal.topstep.com/graphql/q
    """
    DOMAIN = "topstep.com"
    FIRM_NAME = "TopStep"
    REST_BASE = "https://api.topstep.com"
    GQL_URL = "https://crystal.topstep.com/graphql/q"

    def _fetch_ts(self, path, params=None):
        """Fetch from TopStep REST API with cookies."""
        url = f"{self.REST_BASE}{path}"
        if params:
            qs = '&'.join(f"{k}={v}" for k, v in params.items())
            url += f"?{qs}"
        return self._fetch_json(url)

    def _graphql(self, query, variables=None):
        """Execute a GraphQL query against TopStep's Crystal endpoint."""
        body = {'query': query}
        if variables:
            body['variables'] = variables
        headers = {'Content-Type': 'application/json'}

        js = f"""
            (async () => {{
                const r = await fetch({json.dumps(self.GQL_URL)}, {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {json.dumps(headers)},
                    body: JSON.stringify({json.dumps(body)})
                }});
                const text = await r.text();
                return JSON.stringify({{status: r.status, body: text}});
            }})()
        """
        raw = self._js(js, await_promise=True)
        if not raw:
            return None
        result = json.loads(raw)
        if result.get('status') != 200:
            return None
        try:
            return json.loads(result['body'])
        except (json.JSONDecodeError, KeyError):
            return None

    def _get_profile(self):
        return self._fetch_ts('/me/profile/')

    def _get_user_id(self):
        """Extract user ID from profile. Profile: {user: {user: {...}, id: N}}."""
        profile = self._get_profile()
        if not profile:
            return None
        # Try nested user.user structure
        user = profile.get('user', profile)
        if isinstance(user, dict):
            uid = user.get('id', user.get('userId', user.get('legacyAppId')))
            if uid:
                return uid
            inner = user.get('user', {})
            if isinstance(inner, dict):
                return inner.get('legacyAppId', inner.get('id'))
        return None

    def _get_email(self):
        """Extract email from profile."""
        profile = self._get_profile()
        if not profile:
            return None
        user = profile.get('user', profile)
        if isinstance(user, dict):
            email = user.get('email')
            if email:
                return email
            inner = user.get('user', {})
            if isinstance(inner, dict):
                return inner.get('email')
        return None

    def get_account_stats(self):
        """Get account stats from TopStep."""
        with self.lock:
            now = time.time()
            if now - self._stats_last_fetch < 2.0 and self._cached_stats:
                return self._cached_stats

            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Open Trades": "0",
                "Symbol": "",
                "Direction": "",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
            }

            try:
                profile = self._get_profile()
                if profile:
                    # Profile: {user: {user: {email, ...}, id: N}}
                    user = profile.get('user', profile)
                    inner = user.get('user', user) if isinstance(user, dict) else user
                    if isinstance(inner, dict):
                        stats["Account Number"] = inner.get('email', 'Unknown')

                accounts = self._fetch_ts('/me/accounts/basic', {
                    'offset': '0', 'limit': '15',
                    'sortBy': 'createdAt', 'sortOrder': 'desc'
                })
                if accounts:
                    # Response: {accounts: [...], hasMore, total}
                    items = accounts.get('accounts', accounts.get('data', []))
                    if isinstance(items, list) and items:
                        first = items[0]
                        stats["Account Number"] = first.get('accountNumber', first.get('name', stats["Account Number"]))
                        bal = first.get('balance', first.get('accountBalance'))
                        if isinstance(bal, (int, float)):
                            stats["Balance"] = f"${bal:,.2f}"
                        stats["Status"] = first.get('status', 'N/A')
                        stats["Phase"] = first.get('type', first.get('phase', 'N/A'))

            except Exception as e:
                self.logger.warning(f"[STATS] Error: {e}")

            self._cached_stats = stats
            self._stats_last_fetch = now
            return stats

    def get_billing_history(self):
        """Get purchase history via GraphQL."""
        user_id = self._get_user_id()
        if not user_id:
            # Fallback to REST
            result = self._fetch_ts('/me/purchases/')
            if result:
                items = result.get('data', result) if isinstance(result, dict) else result
                return items if isinstance(items, list) else []
            return []

        gql = f"""
        {{
            normalizedPurchasesByUser(userid: {user_id}, first: 100) {{
                nodes {{
                    id
                    source
                    type
                    subtotal
                    discount
                    tax
                    total
                    method
                    createdAt
                }}
            }}
        }}
        """
        result = self._graphql(gql)
        if not result:
            return []
        nodes = (result.get('data', {})
                 .get('normalizedPurchasesByUser', {})
                 .get('nodes', []))
        billing = []
        for item in nodes:
            billing.append({
                "sn": str(item.get("id", "")),
                "account_no": "",
                "status": "APPROVED",
                "date": str(item.get("createdAt", ""))[:10],
                "paid_amount": f"${item.get('total', 0):.2f}",
                "paid_amount_numeric": float(item.get("total", 0) or 0),
                "funding_package": item.get("type", item.get("source", "")),
                "payment_method": item.get("method", ""),
            })
        return billing

    def get_subscriptions(self):
        """Get subscription history via GraphQL."""
        user_id = self._get_user_id()
        if not user_id:
            return []
        gql = f"""
        {{
            normalizedSubsByUser(userid: {user_id}, first: 50) {{
                nodes {{
                    id
                    source
                    productName
                    amount
                    total
                    status
                    createdAt
                }}
            }}
        }}
        """
        result = self._graphql(gql)
        if not result:
            return []
        return (result.get('data', {})
                .get('normalizedSubsByUser', {})
                .get('nodes', []))

    def get_all_accounts(self):
        """Get all accounts from REST."""
        accounts = self._fetch_ts('/me/accounts/basic', {
            'offset': '0', 'limit': '100',
            'sortBy': 'createdAt', 'sortOrder': 'desc'
        })
        if accounts:
            # Response: {accounts: [...], hasMore, total}
            items = accounts.get('accounts', accounts.get('data', []))
            if isinstance(items, list):
                return items
        return []

    def get_payouts(self):
        """Get payouts from REST."""
        result = self._fetch_ts('/me/payouts/')
        if not result:
            return []
        items = result.get('data', result) if isinstance(result, dict) else result
        return items if isinstance(items, list) else []


# ═══════════════════════════════════════════════════════════════════════
#  MFFU (My Funded Futures)
# ═══════════════════════════════════════════════════════════════════════
class MFFUAccount(CDPBase):
    """
    MFFU dashboard scraper — Next.js app at myfundedfutures.com
    Auth: session cookies (credentials: include)
    API base: https://api.myfundedfutures.com/api
    """
    DOMAIN = "myfundedfutures.com"
    FIRM_NAME = "MFFU"
    API_BASE = "https://api.myfundedfutures.com/api"

    def _get_profile(self):
        return self._fetch_json(f"{self.API_BASE}/getProfile/")

    def get_account_stats(self):
        """Get account stats from MFFU profile."""
        with self.lock:
            now = time.time()
            if now - self._stats_last_fetch < 2.0 and self._cached_stats:
                return self._cached_stats

            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Open Trades": "0",
                "Symbol": "",
                "Direction": "",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
            }

            try:
                profile = self._get_profile()
                if profile:
                    # Profile: {business_id, id, username, email, defaultFuturesAccount: {account_name, balance, pnl, status, ...}}
                    stats["Account Number"] = profile.get('username', profile.get('email', 'Unknown'))
                    acct = profile.get('defaultFuturesAccount', profile.get('default_account', {}))
                    if isinstance(acct, dict):
                        stats["Account Number"] = acct.get('account_name', stats["Account Number"])
                        bal = acct.get('balance')
                        if isinstance(bal, (int, float)):
                            stats["Balance"] = f"${bal:,.2f}"
                        drawdown = acct.get('max_drawdown_amount', acct.get('drawdown'))
                        if isinstance(drawdown, (int, float)):
                            stats["Drawdown"] = f"${drawdown:,.2f}"
                        pnl = acct.get('pnl', acct.get('total_pnl'))
                        if isinstance(pnl, (int, float)):
                            stats["Profit/Loss"] = f"${pnl:,.2f}"
                        starting = acct.get('starting_balance')
                        target = acct.get('profit_target')
                        if isinstance(target, (int, float)) and target:
                            stats["Profit Target"] = f"${target:,.2f}"
                        stats["Status"] = acct.get('status', 'N/A')
                        stats["Phase"] = acct.get('stage', 'N/A')

            except Exception as e:
                self.logger.warning(f"[STATS] Error: {e}")

            self._cached_stats = stats
            self._stats_last_fetch = now
            return stats

    def _fetch_post_empty(self, url):
        """POST with no body and no Content-Type (required by some MFFU endpoints)."""
        js = f"""
            (async () => {{
                const r = await fetch({json.dumps(url)}, {{
                    method: 'POST',
                    credentials: 'include'
                }});
                const text = await r.text();
                return JSON.stringify({{status: r.status, body: text}});
            }})()
        """
        raw = self._js(js, await_promise=True)
        if not raw:
            return None
        result = json.loads(raw)
        if result.get('status') != 200:
            self.logger.warning(f"[FETCH] POST {url} \u2192 HTTP {result.get('status')}")
            return None
        try:
            return json.loads(result['body'])
        except (json.JSONDecodeError, KeyError):
            return result.get('body')

    def get_billing_history(self):
        """Get billing history: try DOM scrape first (has account numbers), then API fallback."""
        # DOM scrape is preferred because it includes MFFU account numbers
        # (e.g. MFFUEVSCL223761104) that the API endpoints do not return.
        dom_billing = self._scrape_billing_dom()
        if dom_billing:
            return dom_billing

        # Fallback: API endpoints (subscriptions + receipts)
        billing = []
        _APPROVED = ("active", "paid", "approved", "processed", "completed", "expired")

        subs = self._fetch_post_empty(f"{self.API_BASE}/getSubscriptions/")
        if subs:
            ok = subs.get('ok', subs) if isinstance(subs, dict) else subs
            items = ok.get('subscriptions', ok) if isinstance(ok, dict) else ok
            if isinstance(items, list):
                for item in items:
                    billing.append({
                        "sn": str(item.get("id", "")),
                        "account_no": str(item.get("account_name", item.get("id", ""))),
                        "status": "APPROVED" if str(item.get("status", "")).lower() in _APPROVED else str(item.get("status", "")),
                        "date": str(item.get("created_at", item.get("date", "")))[:10],
                        "paid_amount": f"${item.get('price', item.get('amount', 0))}",
                        "paid_amount_numeric": float(item.get("price", item.get("amount", 0)) or 0),
                        "funding_package": item.get("plan_name", item.get("plan", item.get("name", ""))),
                        "payment_method": item.get("payment_method", ""),
                        "coupon": item.get("coupon_code", ""),
                    })

        receipts = self._fetch_post_empty(f"{self.API_BASE}/getReceipts/")
        if receipts:
            items = receipts.get('ok', receipts) if isinstance(receipts, dict) else receipts
            if isinstance(items, list):
                for item in items:
                    billing.append({
                        "sn": str(item.get("order_number", item.get("id", ""))),
                        "account_no": str(item.get("account_name", "")),
                        "status": "APPROVED" if str(item.get("status", "")).lower() in _APPROVED else str(item.get("status", "")),
                        "date": str(item.get("created_at", item.get("date", "")))[:10],
                        "paid_amount": f"${item.get('price_paid', item.get('amount', 0))}",
                        "paid_amount_numeric": float(item.get("price_paid", item.get("amount", 0)) or 0),
                        "funding_package": item.get("plan_name", item.get("plan", "")),
                    })

        return billing

    def _scrape_billing_dom(self):
        """Scrape billing from the Prop Account Subscriptions table at /billing."""
        # Navigate to billing page
        current = self._js("window.location.href") or ""
        if "/billing" not in current:
            self._js("window.location.href = 'https://myfundedfutures.com/billing'")
            time.sleep(4)

        # Extract all rows from the billing table.
        # Columns: STARTED | ACCOUNT | RENEWS/EXPIRES | PRICE | COUPON | METHOD | STATUS | ACTIONS
        raw = self._js("""
            (function() {
                var rows = document.querySelectorAll('table tbody tr');
                if (rows.length === 0) {
                    // Try alternate selectors for Next.js / Tailwind tables
                    rows = document.querySelectorAll('[class*="billing"] tr, [class*="subscription"] tr');
                }
                var results = [];
                for (var i = 0; i < rows.length; i++) {
                    var cells = rows[i].querySelectorAll('td');
                    if (cells.length < 7) continue;
                    results.push({
                        started: (cells[0] || {}).innerText || '',
                        account: (cells[1] || {}).innerText || '',
                        renews: (cells[2] || {}).innerText || '',
                        price: (cells[3] || {}).innerText || '',
                        coupon: (cells[4] || {}).innerText || '',
                        method: (cells[5] || {}).innerText || '',
                        status: (cells[6] || {}).innerText || ''
                    });
                }
                return JSON.stringify(results);
            })()
        """)

        if not raw:
            self.logger.warning("[BILLING] DOM scrape returned nothing")
            return []

        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning("[BILLING] DOM scrape JSON parse failed")
            return []

        billing = []
        for item in items:
            # Parse account: may contain badge text + account number, e.g. "Scale50K\nMFFUEVSCL223761104"
            acct_text = item.get("account", "").strip()
            acct_lines = [l.strip() for l in acct_text.split("\n") if l.strip()]
            # Account number is typically the longest line starting with MFFU
            account_no = ""
            funding_package = ""
            for line in acct_lines:
                if line.upper().startswith("MFFU"):
                    account_no = line
                elif not funding_package:
                    funding_package = line  # e.g. "Scale50K"

            # Parse price
            price_str = item.get("price", "").strip()
            price_numeric = 0.0
            try:
                price_numeric = float(price_str.replace("$", "").replace(",", "").strip())
            except (ValueError, AttributeError):
                # "Will not renew" or empty
                pass

            # Parse status — map to APPROVED for active/expired paid subscriptions
            status_raw = item.get("status", "").strip().lower()
            if status_raw in ("active", "expired") and price_numeric > 0:
                status = "APPROVED"
            elif status_raw == "cancelled":
                status = "CANCELLED"
            else:
                status = status_raw.upper()

            # Parse date: "Sep 29 2025" → "2025-09-29"
            date_str = item.get("started", "").strip()
            try:
                from datetime import datetime as _dt
                parsed = _dt.strptime(date_str, "%b %d %Y")
                date_str = parsed.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass  # keep as-is

            if account_no and price_numeric > 0:
                billing.append({
                    "sn": account_no,
                    "account_no": account_no,
                    "status": status,
                    "date": date_str,
                    "paid_amount": f"${price_numeric:.2f}",
                    "paid_amount_numeric": price_numeric,
                    "funding_package": funding_package,
                    "payment_method": item.get("method", "").strip(),
                    "coupon": item.get("coupon", "").strip(),
                })

        self.logger.info(f"[BILLING] DOM scrape got {len(billing)} record(s)")
        return billing

    def get_account_mapping(self):
        """Build login_id → account info mapping from MFFU prop accounts.
        Returns dict of account_name → {tradovate_account_name, balance, starting_balance, breached, ...}
        """
        mapping = {}
        accounts = self.get_all_accounts()
        for acct in accounts:
            acct_name = acct.get("account_name", "")
            if not acct_name:
                continue
            balance = acct.get("balance", acct.get("current_balance"))
            starting = acct.get("starting_balance", acct.get("initial_balance"))
            status = acct.get("status", "")
            breached = status.lower() in ("breached", "failed", "blown") if status else False
            # Extract profit target and drawdown limit from the account object
            profit_target = acct.get("profit_target")
            max_dd = acct.get("max_drawdown_amount", acct.get("max_drawdown"))
            min_equity = None
            if starting is not None and max_dd is not None:
                try:
                    min_equity = float(starting) - float(max_dd)
                except (ValueError, TypeError):
                    pass
            mapping[acct_name] = {
                "tradovate_account_name": acct_name,
                "balance": balance,
                "starting_balance": starting,
                "breached": breached,
                "breachedby": acct.get("breached_by", acct.get("breach_reason", "")),
                "status": status,
                "account_id": acct.get("id", ""),
                "profit_target": profit_target,
                "min_equity": min_equity,
            }
        self.logger.info(f"[MAPPING] Got {len(mapping)} MFFU account(s)")
        return mapping

    def get_all_accounts(self):
        """Get all prop accounts (paginated)."""
        all_accounts = []
        page = 1
        while True:
            result = self._fetch_json(
                f"{self.API_BASE}/user-prop-accounts/?page={page}&page_size=100")
            if not result:
                break
            # Response: {ok: {total: N, accounts: [...]}}
            ok = result.get('ok', result) if isinstance(result, dict) else result
            items = ok.get('accounts', ok.get('results', [])) if isinstance(ok, dict) else ok
            if isinstance(items, list):
                all_accounts.extend(items)
            # Check for next page
            total = ok.get('total', 0) if isinstance(ok, dict) else 0
            if len(all_accounts) >= total or not items:
                break
            page += 1
            if page > 10:
                break
        return all_accounts

    def get_payouts(self):
        """Get past payouts (paginated)."""
        all_payouts = []
        page = 0
        while True:
            result = self._fetch_json(
                f"{self.API_BASE}/getPastPayouts/?page={page}&page_size=50")
            if not result:
                break
            ok = result.get('ok', result)
            if isinstance(ok, dict):
                data = ok.get('data', {})
                items = data.get('past_payouts', []) if isinstance(data, dict) else []
                all_payouts.extend(items)
                total = ok.get('total', 0)
                if len(all_payouts) >= total:
                    break
            elif isinstance(ok, list):
                all_payouts.extend(ok)
                break
            else:
                break
            page += 1
            if page > 10:  # Safety limit
                break
        return all_payouts

    def get_available_payouts(self):
        """Get current available and upcoming payouts."""
        result = self._fetch_json(f"{self.API_BASE}/getUserPayoutsPage/")
        if not result:
            return {}
        return result.get('ok', result)

    def get_account_categories(self):
        """Get account category metadata."""
        return self._fetch_json(f"{self.API_BASE}/user-prop-account-categories/")


# ═══════════════════════════════════════════════════════════════════════
#  Quick Test
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
#  FUNDED NEXT  (CDP)
# ═══════════════════════════════════════════════════════════════════════
class FundedNextCDPAccount(CDPBase):
    """
    FundedNext dashboard scraper — CDP-based (no Selenium).
    Connects to https://app.fundednext.com via Chrome DevTools Protocol.
    Auth: tokenV1 cookie → Bearer token for API calls.
    """
    DOMAIN = "fundednext.com"
    FIRM_NAME = "FundedNext"
    API_BASE = "https://api.fundednext.com/api/v1"

    def __init__(self, username=None, debug_port=9222, pair_id="default"):
        super().__init__(debug_port=debug_port, pair_id=pair_id)
        self.username = username or ""

    # ── Auth helpers ──

    def _get_token(self):
        """Extract tokenV1 from browser cookies."""
        return self._js("""
            (function() {
                var c = document.cookie.split(';').find(function(c) {
                    return c.trim().indexOf('tokenV1=') === 0;
                });
                return c ? decodeURIComponent(c.split('=')[1]) : null;
            })()
        """)

    def _get_email(self):
        """Get user email from localStorage or fallback to self.username."""
        if self.username:
            return self.username
        email = self._js("""
            (function() {
                try {
                    var u = JSON.parse(localStorage.getItem('user') || '{}');
                    return u.email || '';
                } catch(e) { return ''; }
            })()
        """)
        return email or ""

    # ── Navigation helpers ──

    def _navigate_to(self, path):
        """Navigate to a FundedNext page by path."""
        current = self._js("window.location.href") or ""
        if path in current:
            return True
        self._js(f"window.location.href = 'https://app.fundednext.com{path}'")
        time.sleep(3)
        return True

    def _switch_type_tab(self, tab_name="Futures"):
        """Click a type tab (Futures / CFDs) via ant-tabs."""
        result = self._js(f"""
            (function() {{
                var tabs = document.querySelectorAll('.ant-tabs-tab-btn');
                for (var i = 0; i < tabs.length; i++) {{
                    if (tabs[i].textContent.trim() === '{tab_name}') {{
                        tabs[i].click();
                        return 'clicked';
                    }}
                }}
                return 'not_found';
            }})()
        """)
        if result == "clicked":
            time.sleep(3)
            return True
        return False

    def _switch_status_tab(self, status="Active"):
        """Click a status tab (Active/Inactive/Breached)."""
        result = self._js(f"""
            (function() {{
                var btns = document.querySelectorAll('.account-wrapper__create-account button');
                for (var i = 0; i < btns.length; i++) {{
                    if (btns[i].textContent.trim() === '{status}') {{
                        btns[i].click();
                        return 'clicked';
                    }}
                }}
                return 'not_found';
            }})()
        """)
        if result == "clicked":
            time.sleep(2)
            return True
        return False

    def _has_accounts(self):
        """Check if current tab view has accounts."""
        return not self._js("""
            (function() {
                var el = document.querySelector('.no-account-wrapper');
                return el && el.offsetParent !== null;
            })()
        """)

    # ── Standard Interface ──

    def get_account_stats(self):
        """Get FundedNext account stats from the dashboard DOM."""
        with self.lock:
            now = time.time()
            if (now - self._stats_last_fetch) < 2.0 and self._cached_stats:
                return self._cached_stats

            if not self.is_connected():
                return self._default_stats("Not Connected")

            self._navigate_to("/accounts")

            stats = self._default_stats("Unknown")

            # Extract all card data in one JS call
            card_data = self._js("""
                (function() {
                    var result = {account: '', balance: '', equity: '', serverType: '',
                                  accountType: '', challenge: '', size: ''};
                    // Account number from .dashboard-card h3
                    var h3s = document.querySelectorAll('.dashboard-card h3');
                    for (var i = 0; i < h3s.length; i++) {
                        var text = h3s[i].textContent;
                        var m = text.match(/FNFT\\w+/);
                        if (m) {
                            result.account = m[0];
                            var parts = text.match(/^(.+?)\\s*\\|\\s*(\\w+)\\s*\\|/);
                            if (parts) { result.challenge = parts[1].trim(); result.size = parts[2].trim(); }
                            break;
                        }
                    }
                    // Balance, Equity, Server Type, Account Type from .active-account-card p
                    var ps = document.querySelectorAll('.active-account-card p');
                    for (var j = 0; j < ps.length; j++) {
                        var t = ps[j].textContent.trim();
                        if (t.indexOf('Balance:') === 0) result.balance = t.split(':')[1].trim();
                        else if (t.indexOf('Equity:') === 0) result.equity = t.split(':')[1].trim();
                        else if (t.indexOf('Server Type:') === 0) result.serverType = t.split(':')[1].trim();
                        else if (t.indexOf('Account Type:') === 0) result.accountType = t.split(':')[1].trim();
                    }
                    return JSON.stringify(result);
                })()
            """)

            if card_data:
                try:
                    d = json.loads(card_data)
                    if d.get("account"):
                        stats["Account Number"] = d["account"]
                    if d.get("balance"):
                        stats["Balance"] = d["balance"]
                    if d.get("equity"):
                        stats["Equity"] = d["equity"]
                    if d.get("challenge"):
                        stats["Phase"] = d["challenge"]
                    if d.get("size"):
                        stats["Size"] = d["size"]
                    if d.get("accountType"):
                        stats["Status"] = d["accountType"]
                except (json.JSONDecodeError, TypeError):
                    pass

            self._cached_stats = stats
            self._stats_last_fetch = now
            return stats

    def _default_stats(self, account_text="N/A"):
        return {
            "Account Number": account_text,
            "Balance": "N/A",
            "Equity": "N/A",
            "Profit/Loss": "N/A",
            "Open Trades": "0",
            "Symbol": "",
            "Direction": "",
            "Drawdown": "N/A",
            "Profit Target": "N/A",
            "Phase": "N/A",
            "Status": "N/A",
        }

    def get_all_accounts(self):
        """Get all accounts from dashboard cards (Futures + CFDs, Active)."""
        if not self.is_connected():
            return []

        with self.lock:
            self._navigate_to("/accounts")
            time.sleep(2)
            accounts = []

            for type_tab in ["Futures", "CFDs"]:
                self._switch_type_tab(type_tab)
                self._switch_status_tab("Active")
                time.sleep(1)

                if not self._has_accounts():
                    continue

                # Parse all .dashboard-card elements in a single JS call
                raw = self._js("""
                    (function() {
                        var cards = document.querySelectorAll('.dashboard-card');
                        var results = [];
                        for (var i = 0; i < cards.length; i++) {
                            var text = cards[i].textContent;
                            if (!text.trim()) continue;
                            var acct = {account: '', balance: '', equity: '',
                                        serverType: '', accountType: '', challenge: '', size: ''};
                            var m = text.match(/FNFT\\w+/);
                            if (m) acct.account = m[0];
                            var parts = text.match(/^(.+?)\\s*\\|\\s*(\\w+)\\s*\\|/);
                            if (parts) { acct.challenge = parts[1].trim(); acct.size = parts[2].trim(); }
                            var lines = text.split('\\n');
                            for (var j = 0; j < lines.length; j++) {
                                var l = lines[j].trim();
                                if (l.indexOf('Balance:') === 0) acct.balance = l.split(':')[1].trim();
                                else if (l.indexOf('Equity:') === 0) acct.equity = l.split(':')[1].trim();
                                else if (l.indexOf('Server Type:') === 0) acct.serverType = l.split(':')[1].trim();
                                else if (l.indexOf('Account Type:') === 0) acct.accountType = l.split(':')[1].trim();
                            }
                            results.push(acct);
                        }
                        return JSON.stringify(results);
                    })()
                """)

                if raw:
                    try:
                        parsed = json.loads(raw)
                        for item in parsed:
                            stats = self._default_stats(item.get("account", "Unknown"))
                            stats["Balance"] = item.get("balance", "N/A")
                            stats["Equity"] = item.get("equity", "N/A")
                            stats["Phase"] = item.get("challenge", "N/A")
                            stats["Size"] = item.get("size", "N/A")
                            stats["Status"] = item.get("accountType", "N/A")
                            stats["Server Type"] = item.get("serverType", "N/A")
                            stats["Type"] = type_tab
                            accounts.append(stats)
                    except (json.JSONDecodeError, TypeError):
                        pass

            self.logger.info(f"[ACCOUNTS] Extracted {len(accounts)} accounts")
            return accounts

    def get_billing_history(self):
        """Fetch billing via FundedNext REST API, with DOM scrape fallback."""
        token = self._get_token()
        if not token:
            self.logger.warning("[BILLING] No tokenV1 cookie found")
            return self._scrape_billing_dom()

        email = self._get_email()
        if not email:
            self.logger.warning("[BILLING] No email available")
            return self._scrape_billing_dom()

        url = f"{self.API_BASE}/pending-payment-history?email={email}&type=1&account_id=&page=1&limit=20"
        data = self._fetch_json_bearer(url, token)
        if not data:
            self.logger.info("[BILLING] API returned empty — falling back to DOM scrape")
            return self._scrape_billing_dom()

        items = data.get("data", {}).get("data", []) if isinstance(data.get("data"), dict) else data.get("data", [])
        if not items:
            self.logger.info("[BILLING] API data empty — falling back to DOM scrape")
            return self._scrape_billing_dom()

        billing = []
        for item in items:
            billing.append({
                "sn": str(item.get("id", "")),
                "account_no": str(item.get("login", "")),
                "payment_method": item.get("payment_method", ""),
                "invoice": item.get("invoice_path", ""),
                "status": "APPROVED" if item.get("status") == 1 else str(item.get("status", "")),
                "date": (item.get("created_at") or "")[:10],
                "transaction_id": item.get("transaction_id", ""),
                "transition_type": item.get("payments_for", ""),
                "paid_amount": f"${item.get('paid_amount', 0):.2f}",
                "funding_package": item.get("funding_package", ""),
                "paid_amount_numeric": float(item.get("paid_amount", 0) or 0),
                "login": item.get("login"),
            })

        self.logger.info(f"[BILLING] Got {len(billing)} records via API")
        return billing

    def _scrape_billing_dom(self):
        """Scrape billing history from the DOM table on /billing/billing-history."""
        self._navigate_to("/billing/billing-history")
        time.sleep(3)

        raw = self._js("""
            (function() {
                var rows = document.querySelectorAll('.ant-table-wrapper table tbody tr.ant-table-row');
                if (rows.length === 0) {
                    rows = document.querySelectorAll('table tbody tr');
                }
                var results = [];
                for (var i = 0; i < rows.length; i++) {
                    var cells = rows[i].querySelectorAll('td');
                    if (cells.length < 9) continue;
                    results.push({
                        sn: cells[0].innerText.trim(),
                        account_no: cells[1].innerText.trim(),
                        payment_method: cells[2].innerText.trim(),
                        status: cells[4].innerText.trim(),
                        date: cells[5].innerText.trim(),
                        transaction_id: cells[6].innerText.trim(),
                        transition_type: cells[7].innerText.trim(),
                        paid_amount: cells[8].innerText.trim(),
                        funding_package: cells[9] ? cells[9].innerText.trim() : ''
                    });
                }
                return JSON.stringify(results);
            })()
        """)

        if not raw:
            return []

        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

        billing = []
        for item in items:
            amount_str = item.get("paid_amount", "0")
            amount_num = 0.0
            try:
                amount_num = float(amount_str.replace("$", "").replace(",", "").strip())
            except (ValueError, AttributeError):
                pass

            billing.append({
                "sn": item.get("sn", ""),
                "account_no": item.get("account_no", ""),
                "payment_method": item.get("payment_method", ""),
                "invoice": "",
                "status": item.get("status", "").upper(),
                "date": item.get("date", ""),
                "transaction_id": item.get("transaction_id", ""),
                "transition_type": item.get("transition_type", ""),
                "paid_amount": f"${amount_num:.2f}" if amount_num else amount_str,
                "funding_package": item.get("funding_package", ""),
                "paid_amount_numeric": amount_num,
                "login": item.get("account_no", ""),
            })

        self.logger.info(f"[BILLING] Got {len(billing)} records via DOM scrape")
        return billing

    def get_payouts(self):
        """FundedNext doesn't have a separate payouts endpoint — included in billing."""
        return []

    def get_account_mapping(self):
        """
        Get mapping from FundedNext login ID to Tradovate account name
        by extracting React fiber props from .dashboard-card elements.
        """
        self._navigate_to("/accounts")
        time.sleep(2)
        self._switch_type_tab("Futures")
        time.sleep(2)

        # Check for page error
        body_text = self._js("document.body.innerText.substring(0, 500)") or ""
        if "Something Went Wrong" in body_text:
            self.logger.warning("[MAPPING] Futures tab returned error page")
            return {}

        raw = self._js("""
            (function() {
                var cards = document.querySelectorAll('.dashboard-card');
                var results = [];
                for (var i = 0; i < cards.length; i++) {
                    var keys = Object.keys(cards[i]);
                    for (var j = 0; j < keys.length; j++) {
                        if (keys[j].indexOf('__reactFiber') !== -1) {
                            var node = cards[i][keys[j]];
                            for (var k = 0; k < 30 && node; k++) {
                                var p = node.memoizedProps;
                                if (p && p.account && p.account.login) {
                                    var acct = p.account;
                                    results.push({
                                        login: acct.login,
                                        account_id: acct.id,
                                        tradovate_name: (acct.tradovate_account_name || {}).tradovate_account_name || null,
                                        plan_title: (acct.plan || {}).title || null,
                                        balance: acct.balance,
                                        starting_balance: acct.starting_balance,
                                        server_type: (acct.server || {}).server_type || null,
                                        breached: acct.breached,
                                        breachedby: acct.breachedby || null,
                                        profit_target: acct.profit_target || acct.target || null,
                                        drawdown: acct.drawdown || acct.max_drawdown || null
                                    });
                                    break;
                                }
                                node = node.return;
                            }
                            break;
                        }
                    }
                }
                return JSON.stringify(results);
            })()
        """)

        mapping = {}
        if raw:
            try:
                accounts = json.loads(raw)
                for acct in accounts:
                    login_id = acct.get("login")
                    if login_id:
                        starting = acct.get("starting_balance")
                        dd = acct.get("drawdown")
                        min_equity = None
                        if starting is not None and dd is not None:
                            try:
                                min_equity = float(starting) - float(dd)
                            except (ValueError, TypeError):
                                pass
                        mapping[str(login_id)] = {
                            "tradovate_account_name": acct.get("tradovate_name"),
                            "account_id": acct.get("account_id"),
                            "plan_title": acct.get("plan_title"),
                            "balance": acct.get("balance"),
                            "starting_balance": starting,
                            "server_type": acct.get("server_type"),
                            "breached": acct.get("breached"),
                            "breachedby": acct.get("breachedby"),
                            "profit_target": acct.get("profit_target"),
                            "min_equity": min_equity,
                        }
                        self.logger.info(
                            f"[MAPPING] login={login_id} -> tradovate={acct.get('tradovate_name')} "
                            f"({acct.get('plan_title')}) target={acct.get('profit_target')} min_eq={min_equity}")
            except (json.JSONDecodeError, TypeError):
                pass

        self.logger.info(f"[MAPPING] Built mapping for {len(mapping)} account(s)")
        return mapping

    def get_account_overview(self, account_id):
        """Get detailed account overview via the FundedNext API."""
        token = self._get_token()
        if not token:
            self.logger.warning("[OVERVIEW] No tokenV1 cookie found")
            return None

        data = self._fetch_json_bearer(
            f"{self.API_BASE}/account-overview?account_id={account_id}", token)
        if not data:
            return None

        overview = data.get("data", {})
        if not overview:
            self.logger.warning(f"[OVERVIEW] Empty data for account_id={account_id}")
            return None

        acct_details = overview.get("account_details", {})
        self.logger.info(
            f"[OVERVIEW] account_id={account_id} | "
            f"name={acct_details.get('account_name')} | "
            f"breached={acct_details.get('breached')}")
        return overview


def quick_test(debug_port=9222):
    """Test all available prop firm scrapers against open Chrome tabs."""
    scrapers = [
        ("Tradeify", TradeifyAccount),
        ("Lucid Trading", LucidTradingAccount),
        ("TopStep", TopStepAccount),
        ("MFFU", MFFUAccount),
        ("FundedNext", FundedNextCDPAccount),
    ]

    for name, cls in scrapers:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        scraper = cls(debug_port=debug_port)
        try:
            scraper.login()
            print(f"  Connected: {scraper.is_connected()}")

            stats = scraper.get_account_stats()
            print(f"\n  Account Stats:")
            for k, v in stats.items():
                print(f"    {k}: {v}")

            accounts = scraper.get_all_accounts()
            print(f"\n  Accounts: {len(accounts)}")
            for i, acct in enumerate(accounts[:3]):
                acct_name = acct.get('accountName', acct.get('account_number', acct.get('name', f'#{i+1}')))
                print(f"    {acct_name}")

            payouts = scraper.get_payouts()
            print(f"  Payouts: {len(payouts)}")

            billing = scraper.get_billing_history()
            print(f"  Billing records: {len(billing)}")

            scraper.close()
        except ConnectionError as e:
            print(f"  Tab not found — skipping ({e})")
        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prop Firm Dashboard Scrapers (CDP)")
    parser.add_argument("--port", type=int, default=9222, help="Chrome remote debugging port")
    parser.add_argument("--firm", choices=["tradeify", "lucid", "topstep", "mffu", "fundednext", "all"], default="all")
    args = parser.parse_args()

    if args.firm == "all":
        quick_test(args.port)
    else:
        cls_map = {
            "tradeify": TradeifyAccount,
            "lucid": LucidTradingAccount,
            "topstep": TopStepAccount,
            "mffu": MFFUAccount,
            "fundednext": FundedNextCDPAccount,
        }
        scraper = cls_map[args.firm](debug_port=args.port)
        scraper.login()
        print(f"Connected: {scraper.is_connected()}")
        stats = scraper.get_account_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        scraper.close()
