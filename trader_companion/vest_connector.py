"""Vest Markets (next.vestmarkets.com) — headless REST client + executor.

Live-verified Oct 2026 against a Vest Capital $5K evaluation. Vest has no
API-key scheme; auth is two-tier and both tiers ROTATE on every refresh:

    USER token    (access 15 min / refresh 30 days)  ← Privy email login once
      └─ POST /v3/auth/account-token {accountId}  (Bearer USER access)
    ACCOUNT token (access 15 min / refresh)         ← trading calls use this

Reusing a stale refresh token returns 401 (code 1002) and kills the chain, so
the client persists the newest tokens to a JSON file after every rotation and
must be the only consumer of that chain (close Chrome after bootstrapping).

Enums are lowercase (``side`` long|short, ``orderType`` market|limit), decimals
are strings, leverage carries 6 decimals, and POST/PUT/DELETE under
``/v3/positions/`` require an ``Idempotency-Key`` UUID header.

    python -m trader_companion.vest_connector status
    python -m trader_companion.vest_connector quote NDX-USD-PERP
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

REST_URL = "https://api-gateway.hz.vestmarkets.com"
WS_URL = "wss://ws.hz.vestmarkets.com/ws?version=1.0"
DEFAULT_SYMBOL = "NDX-USD-PERP"      # Nasdaq-100 perp (USTECH)
WEEKEND_SYMBOL = "BTC-PERP"          # index perps pin to a held mark on weekends
LEVERAGE_DECIMALS = 6
ACCESS_SKEW_MS = 90_000              # refresh this long before expiry
SIZE_SAFETY = 0.97
RISK_BUFFER = 0.95


def default_token_file() -> str:
    env = os.environ.get("VEST_TOKEN_FILE")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vest_session.json")


class VestError(Exception):
    def __init__(self, message, status=None, code=None, payload=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


class VestClient:
    """REST client holding the rotating user/account token chains."""

    def __init__(self, token_file: Optional[str] = None, account_id: Optional[str] = None,
                 base_url: str = REST_URL, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token_file = token_file or default_token_file()
        self.account_id = account_id or os.environ.get("VEST_ACCOUNT_ID") or None
        self.user: dict = {}
        self.account: dict = {}
        self._lock = threading.RLock()
        self._http = requests.Session()
        self._exchange_info: dict = {}
        self._sod_store: dict = {}
        self._load()

    # ── token persistence ────────────────────────────────────────────────

    def _load(self):
        try:
            with open(self.token_file) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self.user = dict(data.get("user") or {})
        self.account = dict(data.get("account") or {})
        if not self.account_id:
            self.account_id = self.account.get("accountId") or data.get("accountId")

    def _save(self):
        tmp = self.token_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"user": self.user, "account": self.account,
                       "accountId": self.account_id,
                       "saved_at": datetime.now(timezone.utc).isoformat()}, f, indent=1)
        os.replace(tmp, self.token_file)
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def import_tokens(self, user: Optional[dict] = None, account: Optional[dict] = None):
        """Seed the chains from a captured auth response (vest_login / vest_probe)."""
        with self._lock:
            if user:
                self.user = dict(user)
            if account:
                self.account = dict(account)
                self.account_id = account.get("accountId") or self.account_id
            self._save()

    @property
    def logged_in(self) -> bool:
        return bool(self.account.get("accessToken")) or bool(self.user.get("refreshToken"))

    # ── auth ─────────────────────────────────────────────────────────────

    @staticmethod
    def _expired(tok: dict, skew_ms: int = ACCESS_SKEW_MS) -> bool:
        exp = tok.get("accessExpiresAtMs")
        if not tok.get("accessToken") or not exp:
            return True
        return time.time() * 1000 >= float(exp) - skew_ms

    def _refresh_chain(self, tok: dict) -> dict:
        rt = tok.get("refreshToken")
        if not rt:
            raise VestError("no refresh token", code="NO_REFRESH")
        r = self._http.post(f"{self.base_url}/v3/auth/refresh",
                            json={"refreshToken": rt, "requestId": str(uuid.uuid4())},
                            timeout=self.timeout)
        if r.status_code != 200:
            raise VestError(f"refresh failed: {r.status_code} {r.text[:200]}",
                            status=r.status_code, code=self._code_of(r))
        return r.json()

    def _mint_account_token(self) -> dict:
        if self._expired(self.user):
            self.user = self._refresh_chain(self.user)
            self._save()
        if not self.account_id:
            self.account_id = self._discover_account_id(self.user["accessToken"])
        r = self._http.post(f"{self.base_url}/v3/auth/account-token",
                            json={"accountId": self.account_id},
                            headers={"Authorization": f"Bearer {self.user['accessToken']}"},
                            timeout=self.timeout)
        if r.status_code != 200:
            raise VestError(f"account-token failed: {r.status_code} {r.text[:200]}",
                            status=r.status_code, code=self._code_of(r))
        return r.json()

    def _discover_account_id(self, user_access: str) -> str:
        r = self._http.get(f"{self.base_url}/v3/capital/accounts/active",
                           headers={"Authorization": f"Bearer {user_access}"}, timeout=self.timeout)
        accts = (r.json().get("accounts") or []) if r.status_code == 200 else []
        if not accts:
            r = self._http.get(f"{self.base_url}/v3/accounts",
                               headers={"Authorization": f"Bearer {user_access}"}, timeout=self.timeout)
            accts = (r.json().get("accounts") or []) if r.status_code == 200 else []
            ids = [a.get("account_id") for a in accts if a.get("active", True)]
        else:
            ids = [a.get("id") for a in accts]
        if not ids:
            raise VestError("no Vest account found for this user", code="NO_ACCOUNT")
        return str(ids[0])

    def login(self) -> bool:
        """Ensure a valid account access token; rotates and persists as needed."""
        with self._lock:
            if not self._expired(self.account):
                return True
            try:
                if self.account.get("refreshToken"):
                    self.account = self._refresh_chain(self.account)
                    self.account_id = self.account.get("accountId") or self.account_id
                    self._save()
                    return True
            except VestError as exc:
                logger.warning("Vest account chain refresh failed (%s); falling back to user chain", exc)
            self.account = self._mint_account_token()
            self.account_id = self.account.get("accountId") or self.account_id
            self._save()
            return True

    def _auth_headers(self) -> dict:
        self.login()
        return {"Authorization": f"Bearer {self.account['accessToken']}"}

    # ── HTTP ─────────────────────────────────────────────────────────────

    @staticmethod
    def _code_of(r) -> Optional[int]:
        try:
            j = r.json()
            return (j.get("detail") or {}).get("code") if "detail" in j else j.get("code")
        except Exception:
            return None

    def _request(self, method: str, path: str, *, auth: bool = True, body=None,
                 params=None, idempotent: bool = False, _retry: bool = True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers.update(self._auth_headers())
        if idempotent or (method != "GET" and path.startswith("/v3/positions/")):
            headers["Idempotency-Key"] = str(uuid.uuid4())
        try:
            r = self._http.request(method, f"{self.base_url}{path}", json=body, params=params,
                                   headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise VestError(f"{method} {path}: {exc}") from exc
        if r.status_code == 401 and auth and _retry:
            with self._lock:
                self.account["accessExpiresAtMs"] = 0   # force rotation
            return self._request(method, path, auth=auth, body=body, params=params,
                                 idempotent=idempotent, _retry=False)
        if r.status_code >= 400:
            code = self._code_of(r)
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            msg = payload.get("msg") if isinstance(payload, dict) else str(payload)[:200]
            raise VestError(f"{method} {path} -> {r.status_code} code={code} {msg}",
                            status=r.status_code, code=code, payload=payload)
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}

    def _get(self, path, **kw):
        return self._request("GET", path, **kw)

    def _post(self, path, body=None, **kw):
        return self._request("POST", path, body=body, **kw)

    # ── public market data ───────────────────────────────────────────────

    def exchange_info(self, refresh: bool = False) -> dict:
        if refresh or not self._exchange_info:
            data = self._get("/v3/exchangeInfo", auth=False)
            self._exchange_info = {s["symbol"]: s for s in data.get("symbols") or []}
        return self._exchange_info

    def symbol_spec(self, symbol: str) -> dict:
        spec = self.exchange_info().get(symbol)
        if not spec:
            raise VestError(f"unknown symbol {symbol}", code="UNKNOWN_SYMBOL")
        return spec

    def ticker(self, symbol: str) -> dict:
        data = self._get("/v3/ticker/latest", auth=False, params={"symbols": symbol})
        for t in data.get("tickers") or []:
            if t.get("symbol") == symbol:
                return t
        raise VestError(f"no ticker for {symbol}", code="NO_TICKER")

    def mark_price(self, symbol: str) -> float:
        return float(self.ticker(symbol)["markPrice"])

    # ── account / positions ──────────────────────────────────────────────

    def accounts(self) -> list:
        return self._get("/v3/accounts").get("accounts") or []

    def balance(self) -> float:
        for a in self.accounts():
            if str(a.get("account_id")) == str(self.account_id):
                return float(a.get("amount") or 0)
        accts = self.accounts()
        return float(accts[0].get("amount") or 0) if accts else 0.0

    def capital_account(self) -> dict:
        """Active Vest Capital (eval/funded) record incl. floors and targets."""
        accts = self._get("/v3/capital/accounts/active").get("accounts") or []
        for a in accts:
            if str(a.get("id")) == str(self.account_id):
                return a
        return accts[0] if accts else {}

    def open_positions(self) -> list:
        return self._get("/v3/positions/opened").get("positions") or []

    def closed_positions(self, since_ms: Optional[int] = None, until_ms: Optional[int] = None,
                         limit: int = 200) -> list:
        now = int(time.time() * 1000)
        params = {"from": int(since_ms or now - 7 * 86_400_000), "to": int(until_ms or now),
                  "limit": limit}
        return self._get("/v3/positions", params=params).get("positions") or []

    def open_position(self, symbol: str, side: str, quantity: str, leverage: float, *,
                      order_type: str = "market", time_in_force: str = "IOC",
                      price: Optional[str] = None, take_profits: Optional[list] = None,
                      stop_losses: Optional[list] = None, reduce_only: bool = False) -> dict:
        side = side.lower()
        side = {"buy": "long", "sell": "short"}.get(side, side)
        if side not in ("long", "short"):
            raise ValueError("side must be long/short (or buy/sell)")
        body = {"symbol": symbol, "side": side, "orderType": order_type.lower(),
                "quantity": str(quantity), "leverage": f"{float(leverage):.{LEVERAGE_DECIMALS}f}",
                "timeInForce": time_in_force, "reduceOnly": bool(reduce_only)}
        if price is not None:
            body["price"] = str(price)
        if take_profits:
            body["takeProfits"] = take_profits
        if stop_losses:
            body["stopLosses"] = stop_losses
        return self._post("/v3/positions/open", body)

    def set_stop_loss(self, position_id: str, trigger_price: str, execution_type: str = "market") -> dict:
        return self._post("/v3/positions/stop-loss",
                          {"positionId": position_id, "executionType": execution_type,
                           "triggerPrice": str(trigger_price)})

    def set_take_profit(self, position_id: str, trigger_price: str, execution_type: str = "market") -> dict:
        return self._post("/v3/positions/take-profit",
                          {"positionId": position_id, "executionType": execution_type,
                           "triggerPrice": str(trigger_price)})

    def close_position(self, position_id: str, symbol: str, leverage: float,
                       order_type: str = "market", limit_price: Optional[str] = None) -> dict:
        body = {"symbol": symbol, "positionId": position_id, "orderType": order_type,
                "leverage": f"{float(leverage):.{LEVERAGE_DECIMALS}f}"}
        if limit_price is not None:
            body["limitPrice"] = str(limit_price)
        return self._post("/v3/positions/close", body)

    def wait_for_position(self, position_id: str, timeout_sec: float = 15.0) -> Optional[dict]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            for p in self.open_positions():
                if str(p.get("positionId")) == str(position_id):
                    return p
            time.sleep(1.0)
        return None

    # ── companion broker facade (same contract as DXTradeBrowserSession) ──

    def account_codes(self) -> list:
        return [str(self.account_id)] if self.account_id else []

    def list_accounts(self) -> list:
        return [{"account_number": str(self.account_id), "account_id": str(self.account_id)}]

    def get_active_account(self):
        return str(self.account_id) if self.account_id else None

    def _code_for(self, account_hint) -> Optional[str]:
        hint = str(account_hint or "").strip().lower()
        if not self.account_id:
            return None
        if not hint:
            return str(self.account_id)
        aid = str(self.account_id).lower()
        if hint == aid or aid.startswith(hint) or aid.endswith(hint) or hint.endswith(aid[-8:]):
            return str(self.account_id)
        return None

    def _sod_balance(self, balance: float) -> float:
        today = self._ny_today()
        rec = self._sod_store.get(self.account_id)
        if not rec or rec.get("date") != today:
            sod = None
            try:
                cap = self.capital_account()
                sod = float(cap.get("daily_reset_balance") or 0) or None
            except VestError:
                pass
            rec = {"date": today, "balance": sod if sod else balance}
            self._sod_store[self.account_id] = rec
        return float(rec["balance"])

    @staticmethod
    def _ny_today() -> str:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        except Exception:
            return datetime.now(timezone.utc).date().isoformat()

    def _daily_pnl(self) -> list:
        days: dict = {}
        try:
            closed = self.closed_positions(since_ms=int(time.time() * 1000) - 30 * 86_400_000)
        except VestError:
            return []
        for p in closed:
            ts = p.get("closeDate")
            if not ts:
                continue
            day = datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc).date().isoformat()
            d = days.setdefault(day, {"date": day, "trades": 0, "net_pnl": 0.0})
            d["trades"] += 1
            d["net_pnl"] += float(p.get("pnl") or 0) - float(p.get("fee") or 0)
        return sorted(days.values(), key=lambda x: x["date"])

    def get_trade_history(self):
        """[{account_name, balance, balance_sod, daily_pnl:[{date,trades,net_pnl}], ...}]"""
        try:
            bal = self.balance()
        except VestError as exc:
            logger.warning("Vest get_trade_history failed: %s", exc)
            return None
        sod = self._sod_balance(bal)
        open_pnl = 0.0
        try:
            open_pnl = sum(float(p.get("pnl") or 0) for p in self.open_positions())
        except VestError:
            pass
        return [{
            "account_name": str(self.account_id),
            "account_code": str(self.account_id),
            "account_id": str(self.account_id),
            "environment": "vest",
            "balance": bal,
            "balance_sod": sod,
            "realized_pnl": bal - sod,
            "open_pnl": open_pnl,
            "daily_pnl": self._daily_pnl(),
            "fills": [],
        }]

    def has_open_position_for_account(self, expected_account=None):
        if expected_account and not self._code_for(expected_account):
            return False, "unknown"
        try:
            pos = self.open_positions()
        except VestError:
            return False, "error"
        if not pos:
            return False, "flat"
        p = pos[0]
        return True, f"{p.get('side')} {p.get('quantity')} {p.get('symbol')}"

    def get_min_equity(self, account_id=None, **_):
        """Floors come from the Vest Capital record (static drawdown + daily loss)."""
        if account_id and not self._code_for(account_id):
            return None
        try:
            bal = self.balance()
            cap = self.capital_account()
        except VestError:
            return None
        sod = self._sod_balance(bal)
        open_pnl = 0.0
        try:
            open_pnl = sum(float(p.get("pnl") or 0) for p in self.open_positions())
        except VestError:
            pass
        eq = bal + open_pnl
        mdd_floor = float(cap.get("max_drawdown_limit") or 0) or None
        daily_floor = float(cap.get("daily_loss_floor") or 0) or None
        floors = [f for f in (mdd_floor, daily_floor) if f]
        min_eq = max(floors) if floors else None
        return {
            "account_id": str(self.account_id), "net_liq": eq, "net_liq_sod": sod,
            "min_equity": min_eq, "trailing_max_drawdown": None,
            "trailing_max_drawdown_limit": mdd_floor, "daily_loss_floor": daily_floor,
            "trailing_mode": "STATIC",
            "drawdown_remaining": (eq - min_eq) if min_eq else None,
            "target_equity": float(cap.get("target_equity") or 0) or None,
            "max_leverage": float(cap.get("max_leverage") or 0) or None,
            "available": bal,
        }

    def get_account_stats(self):
        try:
            bal = self.balance()
        except VestError:
            return {}
        return {"Balance": f"${bal:,.2f}", "Equity": f"${bal:,.2f}", "Account": str(self.account_id)}

    def is_alive(self) -> bool:
        return self.logged_in

    def keepalive(self) -> bool:
        try:
            self.login()
            self.accounts()
            return True
        except VestError as exc:
            logger.warning("Vest keepalive failed: %s", exc)
            return False

    def logout(self):
        pass

    def close(self):
        pass


class VestExecutor:
    """$-denominated bracket on Vest: size from leverage cap, TP/SL as price triggers.

    Quote is USDC and size is in base units, so PnL = quantity × price delta
    and dollars-per-point equals the quantity (same as the DXtrade perps).
    """

    def __init__(self, client: VestClient):
        self.client = client

    def plan_bracket(self, symbol: str, side: str, *, tp_usd: float, sl_usd: float,
                     leverage: Optional[float] = None, ref_price: Optional[float] = None,
                     max_margin_usd: Optional[float] = None,
                     quantity: Optional[float] = None) -> dict:
        side = side.lower()
        side = {"long": "buy", "short": "sell"}.get(side, side)
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        spec = self.client.symbol_spec(symbol)
        if str(spec.get("capitalTradingStatus") or spec.get("tradingStatus")) != "TRADING":
            raise ValueError(f"{symbol} is not trading ({spec.get('capitalTradingStatus')})")
        size_dec = int(spec.get("sizeDecimals") or 4)
        price_dec = int(spec.get("priceDecimals") or 2)
        tick = float(spec.get("minTickSize") or 10 ** -price_dec)
        step = 10 ** -size_dec

        cap = self.client.capital_account()
        balance = self.client.balance()
        max_lev = float(cap.get("max_leverage") or 0) or (1.0 / float(spec.get("capitalInitMarginRatio") or 0.02))
        lev = min(float(leverage or max_lev), max_lev)
        if ref_price is None:
            ref_price = self.client.mark_price(symbol)
        ref_price = float(ref_price)

        if quantity is None:
            budget = max_margin_usd if max_margin_usd is not None else balance * SIZE_SAFETY
            quantity = math.floor(budget * lev / ref_price / step) * step
        quantity = round(float(quantity), size_dec)
        if quantity < step:
            raise ValueError(f"size {quantity} below min {step} for {symbol} (balance ${balance:,.2f}, {lev:g}x)")

        sl_usd_eff = float(sl_usd) * RISK_BUFFER
        tp_pts = float(tp_usd) / quantity
        sl_pts = sl_usd_eff / quantity
        sign = 1 if side == "buy" else -1
        tp_price = round(round((ref_price + sign * tp_pts) / tick) * tick, price_dec)
        sl_price = round(round((ref_price - sign * sl_pts) / tick) * tick, price_dec)
        return {
            "symbol": symbol, "side": side, "vest_side": "long" if side == "buy" else "short",
            "quantity": quantity, "quantity_str": f"{quantity:.{size_dec}f}",
            "ref_price": ref_price,
            "tp_price": tp_price, "sl_price": sl_price,
            "tp_price_str": f"{tp_price:.{price_dec}f}", "sl_price_str": f"{sl_price:.{price_dec}f}",
            "tp_usd": round(float(tp_usd), 2), "sl_usd": round(sl_usd_eff, 2),
            "tp_pts": round(tp_pts, 2), "sl_pts": round(sl_pts, 2),
            "notional": round(quantity * ref_price, 2),
            "margin": round(quantity * ref_price / lev, 2),
            "leverage": lev, "balance": balance, "equity": balance, "available": balance,
            "tick": tick, "size_decimals": size_dec, "price_decimals": price_dec,
            "daily_loss_floor": float(cap.get("daily_loss_floor") or 0) or None,
            "max_drawdown_limit": float(cap.get("max_drawdown_limit") or 0) or None,
            "target_equity": float(cap.get("target_equity") or 0) or None,
        }

    def execute(self, plan: dict, metadata: Optional[dict] = None) -> dict:
        resp = self.client.open_position(
            plan["symbol"], plan["vest_side"], plan["quantity_str"], plan["leverage"],
            take_profits=[{"executionType": "market", "triggerPrice": plan["tp_price_str"]}],
            stop_losses=[{"executionType": "market", "triggerPrice": plan["sl_price_str"]}])
        pid = resp.get("positionId")
        pos = self.client.wait_for_position(pid, timeout_sec=15) if pid else None
        # Inline TP/SL are accepted on open; attach explicitly if the server dropped them.
        if pos is not None:
            try:
                if not pos.get("stopLosses"):
                    self.client.set_stop_loss(pid, plan["sl_price_str"])
                if not pos.get("takeProfits"):
                    self.client.set_take_profit(pid, plan["tp_price_str"])
            except VestError as exc:
                logger.warning("Vest TP/SL attach failed on %s: %s", pid, exc)
        return {"order_ids": [resp.get("orderId")], "position_id": pid, "position": pos, "raw": resp}

    def enter_bracket(self, symbol: str, side: str, *, tp_usd: float, sl_usd: float, **kw) -> tuple:
        plan = self.plan_bracket(symbol, side, tp_usd=tp_usd, sl_usd=sl_usd, **kw)
        return self.execute(plan), plan

    def flatten(self) -> list:
        out = []
        for p in self.client.open_positions():
            try:
                out.append(self.client.close_position(p["positionId"], p["symbol"],
                                                      float(p.get("leverage") or 1)))
            except VestError as exc:
                out.append({"error": str(exc), "positionId": p.get("positionId")})
        return out


def symbol_for_now(weekday: Optional[int] = None) -> str:
    env = os.environ.get("VEST_SYMBOL")
    if env:
        return env
    if weekday is None:
        weekday = datetime.now(timezone.utc).weekday()
    if weekday >= 5:
        return os.environ.get("VEST_WEEKEND_SYMBOL", WEEKEND_SYMBOL)
    return DEFAULT_SYMBOL


def _main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=["status", "quote", "positions", "history", "flatten"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--token-file", default=None)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = VestClient(token_file=a.token_file)
    if a.cmd == "quote":
        print(json.dumps(c.ticker(a.arg or DEFAULT_SYMBOL), indent=1))
        return
    c.login()
    if a.cmd == "status":
        cap = c.capital_account()
        print(json.dumps({"account": c.account_id, "balance": c.balance(),
                          "plan": cap.get("plan_name"), "stage": cap.get("stage"),
                          "status": cap.get("status"),
                          "target_equity": cap.get("target_equity"),
                          "max_drawdown_limit": cap.get("max_drawdown_limit"),
                          "daily_loss_floor": cap.get("daily_loss_floor"),
                          "max_leverage": cap.get("max_leverage"),
                          "min_equity": c.get_min_equity()}, indent=1, default=str))
    elif a.cmd == "positions":
        print(json.dumps(c.open_positions(), indent=1))
    elif a.cmd == "history":
        print(json.dumps(c.get_trade_history(), indent=1))
    elif a.cmd == "flatten":
        print(json.dumps(VestExecutor(c).flatten(), indent=1))


if __name__ == "__main__":
    _main()
