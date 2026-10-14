"""Breakout Prop companion connector: plain-Chrome session + browser-as-API.

Breakout sits behind Cloudflare bot management, so the companion drives a
*normal* Chrome over raw CDP and issues every iapi.breakoutprop.com call from
inside the logged-in tab (see breakout_api.py). Login is Descope's enchanted
link: the user clicks a link in their email; the tab authenticates itself.
If the portal lands on its dashboard instead of the terminal, the session
clicks **Open Terminal** to reach trade.breakoutprop.com.

`BreakoutSession` exposes the same broker facade the companion uses for the
other API-first firms (logged_in, login, account_codes, get_trade_history,
has_open_position_for_account, get_min_equity, get_account_stats, keepalive).
`BreakoutExecutor` turns $ targets into a market order with protection orders.

    python -m trader_companion.breakout_connector status
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from trader_companion import breakout_probe as probe
from trader_companion.breakout_api import BreakoutBrowserAPI
from trader_companion.cdp_capture import CDPCapture

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "XYZ100/USD"
WEEKEND_SYMBOL = "BTC/USD"
PORTAL_DASHBOARD = "portal.breakoutprop.com/app"
SIZE_SAFETY = 0.97
RISK_BUFFER = 0.95
OPEN_TERMINAL_EL = ("[...document.querySelectorAll('button,a')]"
                    ".find(e => /Open Terminal/i.test(e.innerText || ''))")


class BreakoutError(Exception):
    pass


def symbol_for_now(weekday: Optional[int] = None) -> str:
    env = os.environ.get("BREAKOUT_SYMBOL")
    if env:
        return env
    if weekday is None:
        weekday = datetime.now(timezone.utc).weekday()
    if weekday >= 5:
        return os.environ.get("BREAKOUT_WEEKEND_SYMBOL", WEEKEND_SYMBOL)
    return DEFAULT_SYMBOL


class BreakoutSession:
    """Owns the Chrome tab + API facade for one Breakout login."""

    def __init__(self, email: str, port: int = probe.PORT, otp_prompt=None):
        self.email = email
        self.port = port
        self.otp_prompt = otp_prompt
        self.api: Optional[BreakoutBrowserAPI] = None
        self.lock = threading.RLock()
        self._pairs: dict = {}
        self._sod_store: dict = {}

    # ── login / terminal ─────────────────────────────────────────────

    def _cap(self) -> CDPCapture:
        cap = CDPCapture(self.port, probe.HOSTS, "/tmp/breakout_capture/session", url_hint="breakoutprop.com")
        return cap.start()

    @staticmethod
    def ensure_terminal(cap: CDPCapture, wait_sec: int = 30) -> bool:
        """From the portal dashboard click 'Open Terminal' and follow it to the trade app."""
        if probe.on_trade_app(cap):
            return True
        if PORTAL_DASHBOARD not in cap.current_url():
            cap.navigate("https://portal.breakoutprop.com/app/dashboard")
            for _ in range(20):
                time.sleep(1)
                if PORTAL_DASHBOARD in cap.current_url() or probe.on_trade_app(cap):
                    break
        if probe.on_trade_app(cap):
            return True
        clicked = False
        for _ in range(15):
            if cap.eval_js(f"!!{OPEN_TERMINAL_EL}"):
                clicked = probe._click_center(cap, OPEN_TERMINAL_EL)
                break
            time.sleep(1)
        if not clicked:
            cap.navigate(probe.TRADE_URL)
        for _ in range(wait_sec):
            time.sleep(1)
            if probe.on_trade_app(cap):
                return True
            # The button may open a new tab — follow it.
            try:
                for t in cap._targets():
                    if "trade.breakoutprop.com" in (t.get("url") or "") and t.get("id") != cap.target.get("id"):
                        cap.target = t
                        return True
            except Exception:
                pass
        return probe.on_trade_app(cap)

    @property
    def logged_in(self) -> bool:
        if self.api is None:
            return False
        try:
            st, _, _ = self.api.get("/session/expiration")
            return st == 200
        except Exception:
            return False

    def login(self) -> bool:
        """Open/reuse Chrome, run the enchanted-link sign-in, land on the terminal."""
        with self.lock:
            probe.launch_chrome()
            time.sleep(1.5)
            if self.api is not None:
                try:
                    self.api.close()
                except Exception:
                    pass
                self.api = None
            cap = self._cap()
            try:
                if not probe.on_trade_app(cap):
                    st_ok = False
                    try:
                        # Cookie session may still be valid → just need the terminal.
                        tmp = BreakoutBrowserAPI(self.port, url_hint="breakoutprop.com")
                        st, _, _ = tmp.get("/session/expiration")
                        tmp.close()
                        st_ok = st == 200
                    except Exception:
                        st_ok = False
                    if not st_ok:
                        ok = probe.email_login(cap, self.email, otp_prompt=self.otp_prompt or (lambda *_: ""))
                        if not ok and not probe.on_trade_app(cap):
                            if not self.ensure_terminal(cap):
                                raise BreakoutError("Breakout sign-in did not complete (click the emailed link)")
                    if not probe.on_trade_app(cap):
                        if not self.ensure_terminal(cap):
                            raise BreakoutError("could not reach the Breakout trading terminal")
            finally:
                cap.stop()
            time.sleep(3)
            self.api = BreakoutBrowserAPI(self.port, url_hint="trade.breakoutprop.com")
            accts = self.api.accounts()
            if not accts:
                raise BreakoutError("no Breakout prop account visible after login")
            logger.info("Breakout logged in: %s", ", ".join(a.get("id", "?") for a in accts))
            return True

    # ── account facade ───────────────────────────────────────────────

    def _ensure(self) -> BreakoutBrowserAPI:
        if self.api is None:
            raise BreakoutError("Breakout session not logged in")
        return self.api

    def accounts(self) -> list:
        return self._ensure().accounts()

    def account_codes(self) -> list:
        try:
            return [a["id"] for a in self.accounts() if a.get("status", "active") == "active"]
        except Exception:
            return []

    def list_accounts(self) -> list:
        return [{"account_number": c, "account_id": c} for c in self.account_codes()]

    def get_active_account(self):
        codes = self.account_codes()
        return codes[0] if codes else None

    def _code_for(self, account_hint) -> Optional[str]:
        hint = str(account_hint or "").strip().upper().replace(" ", "-")
        codes = self.account_codes()
        if not hint:
            return codes[0] if len(codes) == 1 else None
        for c in codes:
            cu = c.upper()
            if cu == hint or cu.replace("-", "") == hint.replace("-", "") or cu.endswith(hint) or hint.endswith(cu):
                return c
        return None

    def account_record(self, code: str) -> dict:
        return self._ensure().account(code)

    @staticmethod
    def _amt(v) -> float:
        try:
            return float(v.get("amount") if isinstance(v, dict) else (v or 0))
        except (TypeError, ValueError):
            return 0.0

    def pairs(self, code: str, refresh: bool = False) -> dict:
        if refresh or not self._pairs:
            st, _, d = self._ensure().get(f"/prop-trading/v1/markets/external?account_id={code}")
            self._pairs = {p["name"]: p for p in (d or {}).get("pairs") or []} if st == 200 else {}
        return self._pairs

    def mark_price(self, symbol: str) -> float:
        d = self._ensure().markets([symbol])
        for m in ((d or {}).get("result") or {}).get("data") or []:
            if m.get("symbol") == symbol:
                return float(m["price"])
        raise BreakoutError(f"no price for {symbol}")

    def trades(self, code: str) -> list:
        st, _, d = self._ensure().get(f"/trades/history?account_id={code}")
        return ((d or {}).get("result") or {}).get("trades") or [] if st == 200 else []

    def open_positions(self, code: str) -> list:
        st, _, d = self._ensure().get(f"/positions?account_id={code}")
        res = (d or {}).get("result") if st == 200 else None
        if isinstance(res, dict):
            res = res.get("positions") or res.get("data") or []
        return res or []

    def _daily_pnl(self, code: str) -> list:
        days: dict = {}
        for t in self.trades(code):
            if "closing" not in (t.get("misc") or []):
                continue
            try:
                day = datetime.fromtimestamp(float(t["time"]), tz=timezone.utc).date().isoformat()
            except Exception:
                continue
            d = days.setdefault(day, {"date": day, "trades": 0, "net_pnl": 0.0})
            d["trades"] += 1
        # Realised P&L per day is not on the fill rows; take it from the summary.
        return sorted(days.values(), key=lambda x: x["date"])

    def _sod_balance(self, code: str, rec: dict, balance: float) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        sod = self._amt((rec.get("portfolio") or {}).get("balance_at_rollover")) or None
        if sod:
            return sod
        s = self._sod_store.get(code)
        if not s or s.get("date") != today:
            s = {"date": today, "balance": balance}
            self._sod_store[code] = s
        return float(s["balance"])

    def get_trade_history(self):
        """[{account_name, balance, balance_sod, daily_pnl:[{date,trades,net_pnl}], ...}]"""
        out = []
        try:
            accts = self.accounts()
        except Exception as exc:
            logger.warning("Breakout get_trade_history failed: %s", exc)
            return None
        for a in accts:
            code = a["id"]
            pf = a.get("portfolio") or {}
            bal = self._amt(pf.get("balance"))
            sod = self._sod_balance(code, a, bal)
            daily = self._daily_pnl(code)
            if daily:
                daily[-1]["net_pnl"] = self._amt(pf.get("daily_pnl")) or (bal - sod)
            out.append({
                "account_name": code, "account_code": code, "account_id": code,
                "environment": "breakout", "balance": bal, "balance_sod": sod,
                "realized_pnl": self._amt(pf.get("daily_pnl")) or (bal - sod),
                "open_pnl": self._amt(pf.get("upnl")), "daily_pnl": daily, "fills": [],
                "status": a.get("status"), "name": a.get("name"),
            })
        return out

    def has_open_position_for_account(self, expected_account=None):
        code = self._code_for(expected_account)
        if not code:
            return False, "unknown"
        try:
            pos = self.open_positions(code)
            if pos:
                p = pos[0]
                return True, f"{p.get('type') or p.get('side')} {p.get('volume')} {p.get('pair')}"
            ov = self._ensure().overview(code).get("summary") or {}
            if self._amt(ov.get("used_margin")) > 0:
                return True, "open (margin in use)"
        except Exception:
            return False, "error"
        return False, "flat"

    def get_min_equity(self, account_id=None, **_):
        code = self._code_for(account_id)
        if not code:
            return None
        try:
            rec = self.account_record(code)
        except Exception:
            return None
        plan = rec.get("plan") or {}
        pf = rec.get("portfolio") or {}
        bal = self._amt(pf.get("balance"))
        eq = self._amt(pf.get("equity")) or bal
        mdd_floor = self._amt(plan.get("max_drawdown_equity_value")) or None
        daily_floor = self._amt(plan.get("max_daily_loss_equity_value")) or None
        floors = [f for f in (mdd_floor, daily_floor) if f]
        min_eq = max(floors) if floors else None
        return {
            "account_id": code, "net_liq": eq, "net_liq_sod": self._sod_balance(code, rec, bal),
            "min_equity": min_eq, "trailing_max_drawdown": None,
            "trailing_max_drawdown_limit": mdd_floor, "daily_loss_floor": daily_floor,
            "trailing_mode": "STATIC", "drawdown_remaining": (eq - min_eq) if min_eq else None,
            "target_equity": self._amt(plan.get("target_equity_value")) or None,
            "available": self._amt(pf.get("available_margin")),
            "daily_reset_at": pf.get("daily_pnl_window_resets_at"),
        }

    def get_account_stats(self):
        try:
            a = (self.accounts() or [{}])[0]
        except Exception:
            return {}
        pf = a.get("portfolio") or {}
        return {"Balance": f"${self._amt(pf.get('balance')):,.2f}",
                "Equity": f"${self._amt(pf.get('equity')):,.2f}", "Account": a.get("id")}

    def is_alive(self) -> bool:
        return probe._cdp_alive() and self.api is not None

    def keepalive(self) -> bool:
        try:
            st, _, _ = self._ensure().get("/session/expiration")
            if st == 200:
                self._ensure()._fetch("POST", "/session/activity", body={})
                return True
            return False
        except Exception:
            return False

    def close(self):
        if self.api is not None:
            try:
                self.api.close()
            except Exception:
                pass
            self.api = None


class BreakoutExecutor:
    """$-denominated bracket: XYZ100/USD is quoted in USD with 1 unit = $1/pt."""

    def __init__(self, session: BreakoutSession, code: str):
        self.s = session
        self.code = code

    def plan_bracket(self, symbol: str, side: str, *, tp_usd: float, sl_usd: float,
                     leverage: Optional[float] = None, ref_price: Optional[float] = None,
                     max_margin_usd: Optional[float] = None, quantity: Optional[float] = None) -> dict:
        side = side.lower()
        side = {"long": "buy", "short": "sell"}.get(side, side)
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        spec = self.s.pairs(self.code).get(symbol) or {}
        if spec and not str(spec.get("status", "")).endswith("ENABLED"):
            raise ValueError(f"{symbol} not enabled ({spec.get('status')})")
        min_lot = float(spec.get("min_lot") or 0.0001)
        lot_dec = int(spec.get("lot_decimals") or 8)
        tick = float(spec.get("tick_size") or 1)
        price_dec = max(0, -int(math.floor(math.log10(tick)))) if tick < 1 else 0
        es = spec.get("effective_settings") or {}
        max_lev = float(es.get("buy_leverage" if side == "buy" else "sell_leverage")
                        or spec.get("max_leverage") or 10)
        lev = min(float(leverage or max_lev), max_lev)
        rec = self.s.account_record(self.code)
        pf = rec.get("portfolio") or {}
        balance = self.s._amt(pf.get("balance"))
        available = self.s._amt(pf.get("available_margin")) or balance
        if ref_price is None:
            ref_price = self.s.mark_price(symbol)
        ref_price = float(ref_price)
        if quantity is None:
            budget = max_margin_usd if max_margin_usd is not None else available * SIZE_SAFETY
            quantity = budget * lev / ref_price
        step = min_lot
        quantity = math.floor(float(quantity) / step) * step
        quantity = round(quantity, lot_dec)
        if quantity < min_lot:
            raise ValueError(f"size {quantity} below min {min_lot} for {symbol} "
                             f"(available ${available:,.2f}, {lev:g}x)")
        sl_eff = float(sl_usd) * RISK_BUFFER
        tp_pts = float(tp_usd) / quantity
        sl_pts = sl_eff / quantity
        sign = 1 if side == "buy" else -1
        tp_price = round(round((ref_price + sign * tp_pts) / tick) * tick, price_dec)
        sl_price = round(round((ref_price - sign * sl_pts) / tick) * tick, price_dec)
        fmt = (lambda p: f"{p:.{price_dec}f}") if price_dec else (lambda p: str(int(p)))
        return {
            "symbol": symbol, "side": side, "quantity": quantity,
            "quantity_str": f"{quantity:.{lot_dec}f}".rstrip("0").rstrip(".") or "0",
            "ref_price": ref_price, "tp_price": tp_price, "sl_price": sl_price,
            "tp_price_str": fmt(tp_price), "sl_price_str": fmt(sl_price),
            "tp_usd": round(float(tp_usd), 2), "sl_usd": round(sl_eff, 2),
            "tp_pts": round(tp_pts, 2), "sl_pts": round(sl_pts, 2),
            "notional": round(quantity * ref_price, 2), "margin": round(quantity * ref_price / lev, 2),
            "leverage": lev, "balance": balance, "equity": self.s._amt(pf.get("equity")) or balance,
            "available": available, "tick": tick,
        }

    def execute(self, plan: dict, metadata: Optional[dict] = None) -> dict:
        api = self.s._ensure()
        st, d = api.place_market(plan["symbol"], plan["side"], plan["quantity_str"],
                                 take_profit=plan["tp_price_str"], stop_loss=plan["sl_price_str"],
                                 account_id=self.code)
        if st != 200 or not isinstance(d, dict) or (d.get("errors") or []):
            raise BreakoutError(f"order rejected: {st} {json.dumps(d)[:300]}")
        order_id = (d.get("result") or {}).get("order_id")
        pos = None
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                for p in self.s.open_positions(self.code):
                    if str(p.get("pair") or p.get("symbol")) == plan["symbol"]:
                        pos = p
                        break
                if pos is None:
                    ov = api.overview(self.code).get("summary") or {}
                    if self.s._amt(ov.get("used_margin")) > 0:
                        pos = {"pair": plan["symbol"], "margin_in_use": True}
            except Exception:
                pass
            if pos:
                break
        # Position/trade id comes from the fills ledger (position_status "open").
        tid = (pos or {}).get("position_transaction_id") or (pos or {}).get("trade_id") or (pos or {}).get("id")
        if not tid:
            try:
                for t in self.s.trades(self.code):
                    if t.get("position_status") == "open" and str(t.get("pair")) == plan["symbol"]:
                        tid = t.get("transaction_id")
                        break
            except Exception:
                pass
        # Inline protection_orders is honoured (verified live: two propOrderAdded
        # follow the fill); the explicit call is a belt-and-braces no-op when so.
        protected = False
        if tid:
            try:
                st, d = api.protect(tid, take_profit=plan["tp_price_str"], stop_loss=plan["sl_price_str"],
                                    account_id=self.code)
                errs = (d or {}).get("errors") or [] if isinstance(d, dict) else []
                protected = st == 200 or any(e.get("type") == "protection_order_already_exists" for e in errs)
            except Exception as exc:
                logger.warning("Breakout protection check failed on %s: %s", tid, exc)
        return {"order_ids": [order_id], "position": pos, "position_id": tid, "protected": protected, "raw": d}

    def enter_bracket(self, symbol: str, side: str, *, tp_usd: float, sl_usd: float, **kw) -> tuple:
        plan = self.plan_bracket(symbol, side, tp_usd=tp_usd, sl_usd=sl_usd, **kw)
        return self.execute(plan), plan

    def flatten(self) -> list:
        api = self.s._ensure()
        out = []
        ids = set()
        for p in self.s.open_positions(self.code):
            tid = p.get("position_transaction_id") or p.get("trade_id") or p.get("id")
            if tid:
                ids.add(tid)
        if not ids:
            for t in self.s.trades(self.code):
                if t.get("position_status") == "open" or (t.get("position_status") is None
                                                          and "closing" not in (t.get("misc") or [])):
                    ids.add(t.get("transaction_id"))
        for tid in ids:
            st, d = api.close_position(tid, account_id=self.code)
            out.append({"trade_id": tid, "status": st, "resp": d})
        return out


def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    s = BreakoutSession(os.environ.get("BREAKOUT_EMAIL", "joehickenfpf@gmail.com"), otp_prompt=input)
    s.login()
    if cmd == "status":
        print(json.dumps({"accounts": s.account_codes(), "stats": s.get_account_stats(),
                          "min_equity": s.get_min_equity(s.get_active_account()),
                          "open": s.has_open_position_for_account(s.get_active_account())},
                         indent=1, default=str))
    elif cmd == "history":
        print(json.dumps(s.get_trade_history(), indent=1, default=str))
    elif cmd == "plan":
        ex = BreakoutExecutor(s, s.get_active_account())
        print(json.dumps(ex.plan_bracket(symbol_for_now(), sys.argv[2] if len(sys.argv) > 2 else "buy",
                                         tp_usd=float(sys.argv[3]) if len(sys.argv) > 3 else 100,
                                         sl_usd=float(sys.argv[4]) if len(sys.argv) > 4 else 50), indent=1))
    elif cmd == "flatten":
        print(BreakoutExecutor(s, s.get_active_account()).flatten())
    s.close()


if __name__ == "__main__":
    _main()
