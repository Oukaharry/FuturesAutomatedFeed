"""Breakout 'browser-as-API' client: issue iapi.breakoutprop.com calls from inside
the logged-in Chrome tab over raw CDP, so Cloudflare sees ordinary page traffic.

Auth is the Kraken-style cookie session the tab already holds. Mutating calls
need a CSRF token: GET /session/expiration → header x-internal-auth → GET
/csrf/BREAKOUT (header Csrf-Auth) → result.csrf_token → header x-csrf-token.

    python -m trader_companion.breakout_api get /breakout/v1/accounts?venue=breakout_prop
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Optional

import websocket

from trader_companion.cdp_capture import CDPCapture

PORT = 9333
BASE = "https://iapi.breakoutprop.com/api/internal"


def korigin(channel=1, device=1, product=14, feature=0) -> str:
    """Kraken 'X-KOrigin' segmentation: Channel.Web / Device.PC / Product.Breakout, base-32."""
    n = channel + (device << 8) + (product << 16) + feature * 0x1000000
    digits = "0123456789abcdefghijklmnopqrstuv"
    out = ""
    while n:
        out = digits[n % 32] + out
        n //= 32
    return out or "0"


KORIGIN = korigin()


class BreakoutBrowserAPI:
    def __init__(self, port: int = PORT, url_hint: str = "trade.breakoutprop.com"):
        self.cap = CDPCapture(port, ("breakoutprop.com",), "/tmp/breakout_capture/api", url_hint=url_hint)
        self.cap.target = self.cap.pick_target()
        self.cap.ws = websocket.create_connection(self.cap.target["webSocketDebuggerUrl"],
                                                  suppress_origin=True, timeout=60)
        self.cap._thread = threading.Thread(target=self.cap._loop, daemon=True)
        self.cap._thread.start()
        self._csrf: Optional[str] = None
        self.account_id: Optional[str] = None

    # ── low level ────────────────────────────────────────────────────

    def _fetch(self, method: str, path: str, body=None, headers: Optional[dict] = None, timeout=60):
        url = path if path.startswith("http") else BASE + path
        hdrs = {"accept": "application/json", "x-handler-environment": "stable", "X-KOrigin": KORIGIN}
        hdrs.update(headers or {})
        if body is not None:
            hdrs["content-type"] = "application/json"
        js = f"""
        fetch({json.dumps(url)}, {{method: {json.dumps(method)}, credentials: 'include',
               headers: {json.dumps(hdrs)}, body: {json.dumps(json.dumps(body)) if body is not None else 'undefined'}}})
          .then(async r => ({{status: r.status, hdr: Object.fromEntries(r.headers.entries()), text: await r.text()}}))
          .catch(e => ({{status: -1, hdr: {{}}, text: String(e)}}))"""
        res = self.cap.send("Runtime.evaluate", {"expression": js, "awaitPromise": True,
                                                 "returnByValue": True}, timeout=timeout)
        v = ((res or {}).get("result") or {}).get("value") or {}
        try:
            data = json.loads(v.get("text") or "null")
        except ValueError:
            data = v.get("text")
        return v.get("status"), v.get("hdr") or {}, data

    def get(self, path: str):
        return self._fetch("GET", path)

    def csrf(self, force: bool = False) -> str:
        if self._csrf and not force:
            return self._csrf
        st, hdr, _ = self._fetch("GET", "/session/expiration")
        auth = hdr.get("x-internal-auth") or ""
        st, _, data = self._fetch("GET", "/csrf/BREAKOUT", headers={"Csrf-Auth": auth})
        tok = ((data or {}).get("result") or {}).get("csrf_token") if isinstance(data, dict) else None
        if not tok:
            raise RuntimeError(f"csrf failed: {st} {str(data)[:200]}")
        self._csrf = tok
        return tok

    def mutate(self, method: str, path: str, body=None):
        st, hdr, data = self._fetch(method, path, body=body, headers={"x-csrf-token": self.csrf()})
        if st in (401, 403, 419) or (isinstance(data, dict) and any("csrf" in str(e).lower() for e in data.get("errors") or [])):
            st, hdr, data = self._fetch(method, path, body=body, headers={"x-csrf-token": self.csrf(force=True)})
        return st, data

    # ── account / market reads ───────────────────────────────────────

    def accounts(self) -> list:
        st, _, d = self.get("/breakout/v1/accounts?venue=breakout_prop")
        accts = ((d or {}).get("result") or {}).get("accounts") or []
        if accts and not self.account_id:
            self.account_id = accts[0]["id"]
        return accts

    def account(self, account_id: Optional[str] = None) -> dict:
        aid = account_id or self.account_id or (self.accounts() or [{}])[0].get("id")
        st, _, d = self.get(f"/breakout/v1/accounts/get?account_id={aid}")
        return ((d or {}).get("result") or {}).get("account") or {}

    def overview(self, account_id: Optional[str] = None) -> dict:
        aid = account_id or self.account_id
        st, _, d = self.get(f"/prop-trading/v1/accounts/positions/overview?account_id={aid}")
        return d or {}

    def markets(self, symbols: Optional[list] = None) -> dict:
        q = "&".join(f"symbols%5B{i}%5D={s.replace('/', '%2F')}" for i, s in enumerate(symbols or []))
        st, _, d = self.get(f"/markets/all/external-markets?{q + '&' if q else ''}tradable=true&platform=breakout_prop")
        return d or {}

    def positions(self, account_id: Optional[str] = None) -> dict:
        aid = account_id or self.account_id
        st, _, d = self.get(f"/positions?account_id={aid}")
        return d or {}

    def trading_status(self, account_id: Optional[str] = None) -> dict:
        aid = account_id or self.account_id
        st, _, d = self.get(f"/breakout/v1/trading/status?account_id={aid}")
        return d or {}

    # ── trading ──────────────────────────────────────────────────────

    def place_market(self, pair: str, side: str, volume: str, *, take_profit: Optional[str] = None,
                     stop_loss: Optional[str] = None, reduce_only: bool = False, account_id=None):
        aid = account_id or self.account_id
        body = {"order_type": {"market": {}},
                "pair": {"asset_class": "external_pair", "name": pair},
                "side": side.lower(), "volume": str(volume)}
        if reduce_only:
            body["details"] = {"reduce_only": True}
        po = {}
        if stop_loss is not None:
            po["stopLossPrice"] = str(stop_loss)
        if take_profit is not None:
            po["takeProfitPrice"] = str(take_profit)
        if po:
            body["protection_orders"] = po
        return self.mutate("POST", f"/breakout/v1/trading/orders?account_id={aid}", body)

    def protect(self, position_id: str, *, take_profit: Optional[str] = None,
                stop_loss: Optional[str] = None, account_id=None):
        aid = account_id or self.account_id
        body = {"position_id": position_id}
        if take_profit is not None:
            body["take_profit"] = {"price": str(take_profit)}
        if stop_loss is not None:
            body["stop_loss"] = {"price": str(stop_loss)}
        return self.mutate("POST", f"/breakout/v1/trading/orders/protection?account_id={aid}", body)

    def close_position(self, trade_id: str, amount: Optional[str] = None, account_id=None):
        aid = account_id or self.account_id
        q = f"account_id={aid}" + (f"&amount={amount}" if amount else "")
        return self.mutate("DELETE", f"/breakout/v1/trading/positions/{trade_id}/close?{q}")

    def cancel_order(self, order_id: str, account_id=None):
        aid = account_id or self.account_id
        return self.mutate("DELETE", f"/breakout/v1/trading/orders/{order_id}/cancel?account_id={aid}")

    def close(self):
        self.cap.stop()


def _main():
    api = BreakoutBrowserAPI()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "accounts"
    if cmd == "get":
        st, hdr, d = api.get(sys.argv[2])
        print(st); print(json.dumps(d, indent=1)[:6000])
    elif cmd == "accounts":
        print(json.dumps(api.accounts(), indent=1)[:4000])
    elif cmd == "markets":
        print(json.dumps(api.markets(), indent=1)[:12000])
    elif cmd == "positions":
        api.accounts(); print(json.dumps(api.positions(), indent=1)[:4000])
    elif cmd == "status":
        api.accounts(); print(json.dumps(api.trading_status(), indent=1)[:3000])
    api.close()


if __name__ == "__main__":
    _main()
