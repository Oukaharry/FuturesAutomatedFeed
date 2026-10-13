"""DXtrade (Devexperts) REST + Push API connector.

API-first: no browser automation. DXtrade is a white-label platform, so the
same client works against any broker instance that exposes the SCA REST API
at ``https://<host>/dxsca-web``. Tradeify247 (US clients) runs on
``dx.tradeify247.co``; verified live there.

Auth is *token* mode: POST /login with username/domain/password yields a
sessionToken used as ``Authorization: DXAPI <token>`` on every call. The
token expires on inactivity; POST /ping extends it. Order placement is not
idempotent, so every order carries a client-unique ``orderCode`` and a
duplicate is reported as 409 code 100 rather than double-filled.

A bracket (entry + stop-loss + take-profit) is a single POST of an
``IF-THEN`` order group — the two CLOSE legs have quantity 0 and inherit the
parent's filled size — so a lost response can never leave an unprotected
position.

Docs: https://demo.dx.trade/developers/ (DXtrade-REST-API.md, DXtrade-Push-API.md).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests

DEFAULT_TIMEOUT = 20
DEFAULT_DOMAIN = "default"
TRADEIFY247_HOST = "dx.tradeify247.co"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class DXTradeError(RuntimeError):
    """API error with HTTP status and DXtrade's {errorCode, description} body."""

    def __init__(self, status, payload, message=None):
        self.status = status
        body = payload if isinstance(payload, dict) else {"raw": payload}
        self.payload = body
        self.error_code = str(body.get("errorCode") or body.get("error") or "")
        detail = body.get("description") or body.get("message") or body.get("raw") or ""
        super().__init__(message or f"DXtrade {status} code={self.error_code}: {detail}".strip())

    @property
    def is_auth(self) -> bool:
        return self.status == 401

    @property
    def is_duplicate_order(self) -> bool:
        return self.status == 409 and self.error_code == "100"

    @property
    def is_rate_limited(self) -> bool:
        return self.status == 429


class DXTradeClient:
    """Thin, explicit client over the DXtrade SCA REST API (token auth)."""

    def __init__(self, host: str, username: str, password: str,
                 domain: str = DEFAULT_DOMAIN, *, timeout: int = DEFAULT_TIMEOUT,
                 session: requests.Session = None, use_https: bool = True):
        host = str(host or "").strip().rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            self.base_url = host.rstrip("/") + "/dxsca-web"
        else:
            scheme = "https" if use_https else "http"
            self.base_url = f"{scheme}://{host}/dxsca-web"
        if not username or not password:
            raise ValueError("DXtrade username and password are required")
        self.username = str(username).strip()
        self.password = str(password)
        self.domain = str(domain or DEFAULT_DOMAIN).strip()
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session_token: str | None = None
        self.token_timeout: str | None = None
        self._lock = threading.Lock()

    @property
    def host(self) -> str:
        return self.base_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def ws_url(self) -> str:
        # The server confirms this root "can only Upgrade to WebSocket".
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        return f"{scheme}://{self.host}/dxsca-web/?format=JSON"

    @property
    def ws_md_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        return f"{scheme}://{self.host}/dxsca-web/md?format=JSON"

    # ── plumbing ─────────────────────────────────────────────────────────

    def _headers(self, authed: bool = True) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authed and self.session_token:
            headers["Authorization"] = f"DXAPI {self.session_token}"
        return headers

    def _request(self, method: str, path: str, *, params=None, json_body=None,
                 authed: bool = True, retry_auth: bool = True):
        url = f"{self.base_url}{path}"
        resp = self.session.request(
            method, url, params=params, json=json_body,
            headers=self._headers(authed), timeout=self.timeout)
        if resp.status_code == 401 and authed and retry_auth and self.session_token:
            # Token expired on inactivity: re-login once and replay.
            self.login()
            return self._request(method, path, params=params, json_body=json_body,
                                 authed=authed, retry_auth=False)
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            raise DXTradeError(resp.status_code, payload)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def _get(self, path, **params):
        return self._request("GET", path, params={k: v for k, v in params.items()
                                                  if v is not None})

    @staticmethod
    def _acct(code: str) -> str:
        return quote(str(code), safe="")

    # ── session ──────────────────────────────────────────────────────────

    def login(self) -> dict:
        """POST /login → sessionToken. Safe to call again to refresh."""
        with self._lock:
            data = self._request(
                "POST", "/login", authed=False, retry_auth=False,
                json_body={"username": self.username, "domain": self.domain,
                           "password": self.password})
            self.session_token = data.get("sessionToken")
            self.token_timeout = data.get("timeout")
            if not self.session_token:
                raise DXTradeError(200, data, "DXtrade login returned no sessionToken")
            return data

    def ping(self) -> dict:
        """Extend the token's inactivity timeout."""
        data = self._request("POST", "/ping")
        if data.get("sessionToken"):
            self.session_token = data["sessionToken"]
        return data

    def logout(self) -> None:
        try:
            self._request("POST", "/logout", retry_auth=False)
        finally:
            self.session_token = None

    @property
    def logged_in(self) -> bool:
        return bool(self.session_token)

    # ── users / accounts ─────────────────────────────────────────────────

    def get_users(self) -> dict:
        """Logged-in user's details incl. their accounts."""
        return self._get("/users")

    def list_account_codes(self) -> list:
        """Flatten account codes out of /users."""
        data = self.get_users()
        users = data.get("userDetails") if isinstance(data, dict) else data
        if isinstance(users, dict):
            users = [users]
        codes = []
        for u in users or []:
            for acct in (u or {}).get("accounts") or []:
                code = acct.get("account") or acct.get("accountCode") or acct.get("code")
                if code:
                    codes.append(str(code))
        return codes

    def get_metrics(self, account: str) -> dict:
        """equity / balance / availableBalance / openPnL … for one account."""
        data = self._get(f"/accounts/{self._acct(account)}/metrics")
        metrics = data.get("metrics") if isinstance(data, dict) else data
        if isinstance(metrics, list):
            return metrics[0] if metrics else {}
        return metrics or data or {}

    def get_balance(self, account: str) -> float | None:
        m = self.get_metrics(account)
        try:
            return float(m.get("balance"))
        except (TypeError, ValueError):
            return None

    def get_equity(self, account: str) -> float | None:
        m = self.get_metrics(account)
        try:
            return float(m.get("equity"))
        except (TypeError, ValueError):
            return None

    def get_portfolio(self, account: str) -> dict:
        return self._get(f"/accounts/{self._acct(account)}/portfolio")

    # ── positions / orders ───────────────────────────────────────────────

    def list_positions(self, account: str) -> list:
        data = self._get(f"/accounts/{self._acct(account)}/positions")
        positions = data.get("positions") if isinstance(data, dict) else data
        return list(positions or [])

    def has_open_position(self, account: str) -> bool:
        return bool(self.list_positions(account))

    def list_open_orders(self, account: str) -> list:
        data = self._get(f"/accounts/{self._acct(account)}/orders")
        orders = data.get("orders") if isinstance(data, dict) else data
        return list(orders or [])

    def list_order_history(self, account: str, *, from_time: str = None,
                           to_time: str = None, limit: int = None) -> list:
        data = self._get(f"/accounts/{self._acct(account)}/orders/history",
                         **{"from": from_time, "to": to_time, "limit": limit})
        orders = data.get("orders") if isinstance(data, dict) else data
        return list(orders or [])

    def list_transfers(self, account: str, *, from_time: str = None,
                       to_time: str = None) -> list:
        data = self._get(f"/accounts/{self._acct(account)}/transfers",
                         **{"from": from_time, "to": to_time})
        transfers = data.get("transfers") if isinstance(data, dict) else data
        return list(transfers or [])

    def place_orders(self, account: str, body: dict) -> dict:
        """Raw POST /accounts/{code}/orders with a single order or a group."""
        return self._request("POST", f"/accounts/{self._acct(account)}/orders",
                             json_body=body)

    def place_market(self, account: str, *, instrument: str, side: str,
                     quantity: float, order_code: str = None,
                     tif: str = "GTC", metadata: dict = None) -> dict:
        body = {
            "account": account,
            "orderCode": order_code or new_order_code(),
            "type": "MARKET",
            "instrument": instrument,
            "quantity": str(quantity),
            "positionEffect": "OPEN",
            "side": side.upper(),
            "tif": tif,
        }
        if metadata:
            body["metadata"] = metadata
        return self.place_orders(account, body)

    def place_bracket(self, account: str, *, instrument: str, side: str,
                      quantity: float, stop_price: float = None,
                      limit_price: float = None, order_code: str = None,
                      metadata: dict = None) -> dict:
        """Market entry + SL + TP in one IF-THEN group.

        THEN legs are opposite side, CLOSE, quantity 0 (inherit the fill),
        GTC — exactly as the spec requires. Either protection is optional.
        """
        side = side.upper()
        close_side = "SELL" if side == "BUY" else "BUY"
        code = order_code or new_order_code()
        parent = {
            "orderCode": code,
            "type": "MARKET",
            "instrument": instrument,
            "quantity": str(quantity),
            "positionEffect": "OPEN",
            "side": side,
            "tif": "GTC",
        }
        if metadata:
            parent["metadata"] = metadata
        orders = [parent]
        if stop_price is not None:
            orders.append({
                "orderCode": f"{code}-sl",
                "type": "STOP",
                "instrument": instrument,
                "quantity": "0",
                "positionEffect": "CLOSE",
                "side": close_side,
                "stopPrice": str(stop_price),
                "tif": "GTC",
            })
        if limit_price is not None:
            orders.append({
                "orderCode": f"{code}-tp",
                "type": "LIMIT",
                "instrument": instrument,
                "quantity": "0",
                "positionEffect": "CLOSE",
                "side": close_side,
                "limitPrice": str(limit_price),
                "tif": "GTC",
            })
        if len(orders) == 1:
            return self.place_orders(account, parent)
        return self.place_orders(account, {"orders": orders, "contingencyType": "IF-THEN"})

    def attach_protection(self, account: str, *, position_code: str,
                          instrument: str, close_side: str,
                          stop_price: float = None, limit_price: float = None) -> dict:
        """Add SL or TP to an already-open position (one protection per call)."""
        if (stop_price is None) == (limit_price is None):
            raise ValueError("pass exactly one of stop_price / limit_price")
        body = {
            "account": account,
            "orderCode": new_order_code(),
            "type": "STOP" if stop_price is not None else "LIMIT",
            "instrument": instrument,
            "positionEffect": "CLOSE",
            "positionCode": str(position_code),
            "side": close_side.upper(),
            "tif": "GTC",
        }
        if stop_price is not None:
            body["stopPrice"] = str(stop_price)
        else:
            body["limitPrice"] = str(limit_price)
        return self.place_orders(account, body)

    def close_position(self, account: str, *, position_code: str,
                       instrument: str, close_side: str) -> dict:
        """Market-close a position (quantity inherited from the position)."""
        body = {
            "account": account,
            "orderCode": new_order_code(),
            "type": "MARKET",
            "instrument": instrument,
            "positionEffect": "CLOSE",
            "positionCode": str(position_code),
            "side": close_side.upper(),
            "tif": "GTC",
        }
        return self.place_orders(account, body)

    def cancel_order(self, account: str, order_code: str) -> dict:
        return self._request(
            "DELETE", f"/accounts/{self._acct(account)}/orders/{quote(str(order_code), safe='')}")

    def bulk_close(self, account: str, body: dict = None) -> dict:
        return self._request("POST", f"/accounts/{self._acct(account)}/bulk-close",
                             json_body=body or {})

    # ── reference / market data ──────────────────────────────────────────

    def list_instruments(self, *, symbols: str = None, types: str = None,
                         limit: int = None, start_from: int = None,
                         account: str = None) -> list:
        """GET /instruments/query (or account-scoped). `symbols` accepts `*`."""
        prefix = f"/accounts/{self._acct(account)}" if account else ""
        data = self._get(f"{prefix}/instruments/query", symbols=symbols, types=types,
                         limit=limit, **{"start-from": start_from})
        items = data.get("instruments") if isinstance(data, dict) else data
        return list(items or [])

    def get_instrument(self, symbol: str, account: str = None) -> dict:
        prefix = f"/accounts/{self._acct(account)}" if account else ""
        data = self._get(f"{prefix}/instruments/{quote(str(symbol), safe='')}")
        items = data.get("instruments") if isinstance(data, dict) else data
        if isinstance(items, list):
            return items[0] if items else {}
        return items or data or {}

    def request_market_data(self, account: str, symbols: list,
                            event_types: list) -> dict:
        """One-shot snapshot of quotes/candles via REST (Push API for streams)."""
        return self._request("POST", "/marketdata", json_body={
            "account": account, "symbols": list(symbols), "eventTypes": event_types})

    def get_quote(self, account: str, symbol: str) -> dict | None:
        data = self.request_market_data(
            account, [symbol], [{"type": "Quote", "format": "COMPACT"}])
        events = (data or {}).get("events") or []
        for ev in events:
            if str(ev.get("symbol")) == str(symbol):
                return ev
        return events[0] if events else None

    # ── convenience ──────────────────────────────────────────────────────

    def wait_for_position(self, account: str, timeout_sec: float = 15,
                          poll_sec: float = 0.5) -> list:
        """Poll until at least one position shows (market fill confirmation)."""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            positions = self.list_positions(account)
            if positions:
                return positions
            time.sleep(poll_sec)
        return []


def new_order_code(prefix: str = "tops") -> str:
    """Client-unique order code; DXtrade dedupes on it per account."""
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


class DXTradePushSession:
    """Minimal Push API websocket helper (business events or market data).

    Requires the ``websocket-client`` package. Handles the server's
    PingRequest → Ping handshake so the session token stays alive; callers
    subscribe with build_* helpers and consume messages via on_message.
    """

    def __init__(self, client: DXTradeClient, *, market_data: bool = False,
                 on_message=None, on_error=None, on_close=None):
        self.client = client
        self.url = client.ws_md_url if market_data else client.ws_url
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self._ws = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        try:
            import websocket  # websocket-client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install websocket-client for DXtrade Push API") from exc
        if not self.client.session_token:
            self.client.login()

        def _on_message(ws, raw):
            try:
                msg = json.loads(raw)
            except ValueError:
                return
            if msg.get("type") == "PingRequest":
                ws.send(json.dumps({
                    "type": "Ping",
                    "session": self.client.session_token,
                    "timestamp": _utc_now_iso(),
                }))
                return
            if self.on_message:
                self.on_message(msg)

        def _on_error(ws, err):
            if self.on_error:
                self.on_error(err)

        def _on_close(ws, code, reason):
            if self.on_close:
                self.on_close(code, reason)

        self._ws = websocket.WebSocketApp(
            self.url, on_message=_on_message, on_error=_on_error, on_close=_on_close)
        self._stop.clear()
        self._thread = threading.Thread(
            target=lambda: self._ws.run_forever(ping_interval=0),
            daemon=True, name="dxtrade-push")
        self._thread.start()
        return self

    def send(self, msg: dict):
        if not self._ws:
            raise RuntimeError("Push session not started")
        msg.setdefault("session", self.client.session_token)
        msg.setdefault("timestamp", _utc_now_iso())
        msg.setdefault("requestId", uuid.uuid4().hex[:12])
        self._ws.send(json.dumps(msg))
        return msg["requestId"]

    def subscribe_market_data(self, account: str, symbols: list, *,
                              quotes: bool = True, candle_type: str = None,
                              from_time: str = None, to_time: str = None) -> str:
        event_types = []
        if quotes:
            event_types.append({"type": "Quote", "format": "COMPACT"})
        if candle_type:
            c = {"type": "Candle", "candleType": candle_type, "format": "COMPACT"}
            if from_time:
                c["fromTime"] = from_time
            if to_time:
                c["toTime"] = to_time
            event_types.append(c)
        return self.send({
            "type": "MarketDataSubscriptionRequest",
            "payload": {"account": account, "symbols": list(symbols),
                        "eventTypes": event_types},
        })

    def subscribe_account_metrics(self, accounts: list) -> str:
        return self.send({
            "type": "AccountMetricsSubscriptionRequest",
            "payload": {"accounts": list(accounts)},
        })

    def subscribe_account_portfolios(self, accounts: list) -> str:
        return self.send({
            "type": "AccountPortfoliosSubscriptionRequest",
            "payload": {"accounts": list(accounts)},
        })

    def stop(self):
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
