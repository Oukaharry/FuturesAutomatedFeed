"""Tradeify247 client portal (app.tradeify247.co, Axcera CRM) — billing lookup.

The DXtrade terminal knows nothing about what an account cost; the portal's
Billing page does. Sign in with the portal email/password (the "Login ID" /
"Password" cells on the dashboard's Prop Firm Accounts tab), then read the
user's orders and map each paid order to the trading login it created.

API (reverse-engineered from the Next.js bundle, Oct 2026):
    POST /auth/signin {email, password, ipAddress}      cookie session
    GET  /auth/v1/me                                    → {_id, email, …}
    GET  /order/user/{userId}?status=                   → {data: [order…]}
         order: {_id, orderId, status, createdAt, total, currency_symbol,
                 order{payment_method_title}, propAccount{traderAccountLogin}}

    python -m trader_companion.tradeify247_portal you@example.com
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, Optional

import requests

API_URL = "https://api.app.tradeify247.co"
APP_URL = "https://app.tradeify247.co"
PAID_STATUSES = {"paid", "completed", "complete", "success", "succeeded"}
logger = logging.getLogger("TradeOpssAI.tradeify247_portal")


class Tradeify247PortalError(Exception):
    pass


class Tradeify247Portal:
    def __init__(self, email: str, password: str, timeout: float = 30.0):
        self.email = (email or "").strip().lower()
        self.password = password or ""
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Origin": APP_URL,
            "Referer": APP_URL + "/",
        })
        self.user: dict = {}

    # ── auth ─────────────────────────────────────────────────────────────

    def _ip(self) -> str:
        try:
            return self.s.get("https://api.ipify.org?format=json", timeout=10).json().get("ip") or "0.0.0.0"
        except Exception:
            return "0.0.0.0"

    def login(self) -> dict:
        if not self.email or not self.password:
            raise Tradeify247PortalError("portal email/password missing")
        r = self.s.post(f"{API_URL}/auth/signin",
                        json={"email": self.email, "password": self.password, "ipAddress": self._ip()},
                        timeout=self.timeout)
        body = _json(r)
        if r.status_code != 200:
            raise Tradeify247PortalError(
                f"sign-in failed ({r.status_code}): {body.get('message') if isinstance(body, dict) else r.text[:160]}")
        token = None
        if isinstance(body, dict):
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            token = body.get("token") or body.get("accessToken") or data.get("token") or data.get("accessToken")
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        self.user = self.me()
        return self.user

    def me(self) -> dict:
        r = self.s.get(f"{API_URL}/auth/v1/me", timeout=self.timeout)
        body = _json(r)
        if r.status_code != 200 or not isinstance(body, dict):
            raise Tradeify247PortalError(f"/auth/v1/me failed ({r.status_code})")
        return body.get("data") if isinstance(body.get("data"), dict) and body.get("data", {}).get("_id") else body

    # ── billing ──────────────────────────────────────────────────────────

    def orders(self, status: str = "") -> list:
        uid = (self.user or {}).get("_id")
        if not uid:
            self.user = self.me()
            uid = self.user.get("_id")
        if not uid:
            raise Tradeify247PortalError("portal user id not found")
        r = self.s.get(f"{API_URL}/order/user/{uid}", params={"status": status}, timeout=self.timeout)
        body = _json(r)
        if r.status_code != 200:
            raise Tradeify247PortalError(f"orders failed ({r.status_code})")
        if isinstance(body, dict):
            body = body.get("data") or body.get("orders") or []
        return body if isinstance(body, list) else []

    @staticmethod
    def order_login(order: dict) -> str:
        pa = order.get("propAccount") or {}
        if isinstance(pa, list):
            pa = pa[0] if pa else {}
        return str(pa.get("traderAccountLogin") or pa.get("login") or order.get("traderAccountLogin") or "").strip()

    @staticmethod
    def order_total(order: dict) -> Optional[float]:
        for key in ("total", "amount", "price"):
            v = order.get(key)
            if v in (None, ""):
                v = (order.get("order") or {}).get(key) if isinstance(order.get("order"), dict) else None
            if v not in (None, ""):
                try:
                    return float(str(v).replace(",", "").replace("$", ""))
                except ValueError:
                    continue
        return None

    def fees_by_login(self, paid_only: bool = True) -> Dict[str, float]:
        """{trading login → amount paid} across the user's orders (latest wins)."""
        out: Dict[str, float] = {}
        rows = sorted(self.orders(), key=lambda o: str(o.get("createdAt") or ""))
        for o in rows:
            if paid_only and str(o.get("status") or "").lower() not in PAID_STATUSES:
                continue
            login = self.order_login(o)
            total = self.order_total(o)
            if login and total is not None:
                out[login] = total
                out[login.upper()] = total
        return out


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {}


def fetch_fees(email: str, password: str) -> Dict[str, float]:
    """Convenience: sign in and return {login: fee}; raises on failure."""
    p = Tradeify247Portal(email, password)
    p.login()
    return p.fees_by_login()


def _main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    email = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRADEIFY247_PORTAL_EMAIL", "")
    password = os.environ.get("TRADEIFY247_PORTAL_PASSWORD") or ""
    if not password:
        import getpass
        password = getpass.getpass("Portal password: ")
    p = Tradeify247Portal(email, password)
    me = p.login()
    print("user:", me.get("_id"), me.get("email"))
    for o in p.orders():
        print(f"  #{o.get('orderId')} {str(o.get('createdAt'))[:10]} {o.get('status')} "
              f"{o.get('currency_symbol') or '$'}{p.order_total(o)} → login {p.order_login(o) or '?'}")
    print("fees:", p.fees_by_login())


if __name__ == "__main__":
    _main()
