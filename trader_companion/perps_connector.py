"""MyFundedPerps REST API connector (beta API).

API-first prop firm: no browser automation. A key's prefix picks the host —
fp_test_ keys reach sandbox accounts on sandbox.myfundedperpetuals.com,
fp_live_ keys reach challenge accounts on developers.myfundedperpetuals.com.
Auth is a plain Bearer header; order creation carries an Idempotency-Key and
a client_order_id so lost responses can be recovered via the order list.

Docs: https://docs.myfundedperpetuals.com (OpenAPI at /openapi.yaml).
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import quote

import requests

LIVE_BASE = "https://developers.myfundedperpetuals.com/v1"
SANDBOX_BASE = "https://sandbox.myfundedperpetuals.com/v1"
DEFAULT_TIMEOUT = 20


class MFPError(RuntimeError):
    """API error with HTTP status and the server's error payload."""

    def __init__(self, status, payload, message=None):
        self.status = status
        self.payload = payload if isinstance(payload, dict) else {"raw": payload}
        code = self.payload.get("error") or self.payload.get("code") or ""
        detail = self.payload.get("message") or self.payload.get("detail") or ""
        super().__init__(message or f"MFP API {status} {code}: {detail}".strip())


def base_url_for_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if key.startswith("fp_test_"):
        return SANDBOX_BASE
    return LIVE_BASE


class MFPClient:
    """Thin, explicit client over the MyFundedPerps v1 REST API."""

    def __init__(self, api_key: str, base_url: str = None,
                 timeout: int = DEFAULT_TIMEOUT, session: requests.Session = None):
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("MyFundedPerps API key required (fp_test_... or fp_live_...)")
        self.base_url = (base_url or base_url_for_key(self.api_key)).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    @property
    def is_sandbox(self) -> bool:
        return "sandbox" in self.base_url

    # ── plumbing ─────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, *, params=None, json=None,
                 idempotency_key: str = None):
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = self.session.request(
            method, f"{self.base_url}{path}", params=params, json=json,
            headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            raise MFPError(resp.status_code, payload)
        if not resp.content:
            return {}
        return resp.json()

    def _get(self, path, **params):
        return self._request("GET", path, params={k: v for k, v in params.items()
                                                  if v is not None})

    # ── general / markets ────────────────────────────────────────────────

    def api_info(self):
        return self._get("/")

    def list_markets(self):
        """Tradable instruments with venue, size_step, min_size, min_notional."""
        return self._get("/markets")

    def get_market(self, market_id: str):
        return self._get(f"/markets/{quote(market_id, safe='')}")

    def get_quote(self, market_id: str, side: str = None, size: float = None):
        """Best bid/ask/mid; with side+size also estimated fill/notional/fee."""
        return self._get(f"/markets/{quote(market_id, safe='')}/quote",
                         side=side, size=size)

    # ── accounts ─────────────────────────────────────────────────────────

    def list_accounts(self):
        return self._get("/accounts")

    def get_account(self, account_id: str):
        """Identity, realized balance, and a fresh risk snapshot (loss floors,
        room above each floor, remaining profit target)."""
        return self._get(f"/accounts/{quote(str(account_id), safe='')}")

    def get_trading_policy(self, account_id: str):
        """Effective rules, limits, restrictions, locks, and halts (advisory)."""
        return self._get(f"/accounts/{quote(str(account_id), safe='')}/trading-policy")

    def cancel_all_orders(self, account_id: str, idempotency_key: str = None):
        return self._request(
            "POST", f"/accounts/{quote(str(account_id), safe='')}/cancel-all-orders",
            idempotency_key=idempotency_key or f"cancel-all-{uuid.uuid4().hex}")

    def close_all_positions(self, account_id: str, idempotency_key: str = None):
        return self._request(
            "POST", f"/accounts/{quote(str(account_id), safe='')}/close-all-positions",
            idempotency_key=idempotency_key or f"close-all-{uuid.uuid4().hex}")

    # ── positions ────────────────────────────────────────────────────────

    def list_positions(self, account_id: str = None):
        return self._get("/positions", account_id=account_id)

    def get_position(self, position_id: str):
        return self._get(f"/positions/{quote(str(position_id), safe='')}")

    def close_position(self, position_id: str, size: float = None,
                       idempotency_key: str = None):
        """Reduce-only close; omit size to close the whole position."""
        body = {}
        if size is not None:
            body["size"] = size
        return self._request(
            "POST", f"/positions/{quote(str(position_id), safe='')}/close",
            json=body or None,
            idempotency_key=idempotency_key or f"close-{uuid.uuid4().hex}")

    def update_position_tpsl(self, position_id: str, operations: list,
                             idempotency_key: str = None):
        return self._request(
            "POST", f"/positions/{quote(str(position_id), safe='')}/tpsl",
            json={"operations": operations},
            idempotency_key=idempotency_key or f"tpsl-{uuid.uuid4().hex}")

    # ── orders ───────────────────────────────────────────────────────────

    def place_order(self, *, account_id: str, market_id: str, side: str,
                    size: float, expected_price: float = None,
                    order_type: str = None, price: float = None,
                    leverage: float = None, margin_mode: str = None,
                    take_profit: float = None, stop_loss: float = None,
                    client_order_id: str = None, idempotency_key: str = None,
                    **extra):
        """Market by default; pass order_type/price for limit/stop/take etc."""
        body = {
            "account_id": account_id,
            "market_id": market_id,
            "side": side,
            "size": size,
            "client_order_id": client_order_id or f"tradeops-{uuid.uuid4().hex[:18]}",
        }
        if expected_price is not None:
            body["expected_price"] = expected_price
        if order_type:
            body["type"] = order_type
        if price is not None:
            body["price"] = price
        if leverage is not None:
            body["leverage"] = leverage
        if margin_mode:
            body["margin_mode"] = margin_mode
        if take_profit is not None:
            body["take_profit"] = take_profit
        if stop_loss is not None:
            body["stop_loss"] = stop_loss
        body.update(extra)
        return self._request(
            "POST", "/orders", json=body,
            idempotency_key=idempotency_key or f"order-{uuid.uuid4().hex}")

    def get_order(self, order_id: str):
        return self._get(f"/orders/{quote(str(order_id), safe='')}")

    def list_orders(self, account_id: str = None, client_order_id: str = None,
                    cursor: str = None):
        return self._get("/orders", account_id=account_id,
                         client_order_id=client_order_id, cursor=cursor)

    def cancel_order(self, order_id: str):
        return self._request(
            "DELETE", f"/orders/{quote(str(order_id), safe='')}")

    def modify_order(self, order_id: str, *, price: float = None,
                     size: float = None):
        body = {}
        if price is not None:
            body["price"] = price
        if size is not None:
            body["size"] = size
        return self._request(
            "PATCH", f"/orders/{quote(str(order_id), safe='')}", json=body)

    def list_fills(self, account_id: str = None, cursor: str = None):
        return self._get("/fills", account_id=account_id, cursor=cursor)

    # ── convenience ──────────────────────────────────────────────────────

    def wait_for_order(self, order_id: str, timeout_sec: float = 15,
                       poll_sec: float = 0.5):
        """Poll until the order leaves pending (filled/rejected/cancelled)."""
        deadline = time.time() + timeout_sec
        order = self.get_order(order_id)
        while time.time() < deadline:
            status = str(order.get("status") or "").lower()
            if status and status not in ("pending", "working", "new", "accepted"):
                return order
            time.sleep(poll_sec)
            order = self.get_order(order_id)
        return order

    def market_order_with_quote(self, *, account_id: str, market_id: str,
                                side: str, size: float, leverage: float = None,
                                margin_mode: str = "cross",
                                take_profit: float = None, stop_loss: float = None):
        """Quote first (server-observed price recorded), then market order."""
        q = self.get_quote(market_id, side=side, size=size)
        return self.place_order(
            account_id=account_id, market_id=market_id, side=side, size=size,
            expected_price=q.get("mid"), leverage=leverage,
            margin_mode=margin_mode, take_profit=take_profit,
            stop_loss=stop_loss), q
