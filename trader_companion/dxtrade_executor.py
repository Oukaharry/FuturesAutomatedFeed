"""DXtrade bracket executor: $-denominated exits, sized from account rules.

DXtrade "FOREX"-typed synthetic perps (XYZ100/USD, BTC/USD …) have
lotSize 1 and multiplier 1, so **PnL = quantity × price points** and
dollars-per-point equals the quantity. We size the entry so margin
(notional × marginRate) stays under available balance with a safety
haircut, then convert dollar TP/SL into price distances. The stop never
risks more than the room the account has left.

The broker does not grant the market-data API to client accounts, so the
reference price is passed in (read from the Chrome terminal's depth widget
by DXTradeBrowserSession.quote) or derived from the open position.
"""

from __future__ import annotations

import math
from typing import Optional

from trader_companion.dxtrade_connector import DXTradeClient, DXTradeError

SIZE_SAFETY = 0.97       # margin headroom for fees/slippage
RISK_BUFFER = 0.95       # slice of loss room kept for slippage
DEFAULT_MIN_SIZE = 0.01
DEFAULT_STEP = 0.01
DEFAULT_MARGIN_RATE = 0.5


class DXTradeExecutor:
    def __init__(self, client: DXTradeClient, account: str):
        self.client = client
        self.account = account
        self._rules_cache: dict = {}

    # ── instrument rules ─────────────────────────────────────────────────

    def instrument_rules(self, symbol: str) -> dict:
        """minOrderSize / step / marginRate for this account+symbol (cached)."""
        if symbol in self._rules_cache:
            return self._rules_cache[symbol]
        rules = {"min_size": DEFAULT_MIN_SIZE, "step": DEFAULT_STEP,
                 "margin_rate": DEFAULT_MARGIN_RATE, "status": "UNKNOWN"}
        try:
            data = self.client._get(
                f"/accounts/{self.client._acct(self.account)}/instruments/"
                f"{symbol.replace('/', '%2F')}")
            det = data.get("instrumentDetails") if isinstance(data, dict) else None
            det = det[0] if isinstance(det, list) and det else det
            if isinstance(det, dict):
                rules["min_size"] = float(det.get("minOrderSize") or DEFAULT_MIN_SIZE)
                rules["step"] = float(det.get("minOrderSizeIncrement") or DEFAULT_STEP)
                tiers = ((det.get("marginRate") or {}).get("tiers") or [])
                if tiers:
                    rules["margin_rate"] = float(tiers[0].get("value") or DEFAULT_MARGIN_RATE)
                rules["status"] = str(det.get("tradingStatus") or "UNKNOWN")
        except DXTradeError:
            pass
        self._rules_cache[symbol] = rules
        return rules

    # ── planning ─────────────────────────────────────────────────────────

    def plan_bracket(self, symbol: str, side: str, *, ref_price: float,
                     tp_usd: float, sl_usd: float,
                     max_margin_usd: Optional[float] = None,
                     quantity: Optional[float] = None) -> dict:
        """Dollar targets → quantity + TP/SL prices.

        quantity: fixed size (lots). If None, size to max_margin_usd
        (default: availableBalance × SIZE_SAFETY).
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        rules = self.instrument_rules(symbol)
        if rules["status"] not in ("UNKNOWN", "FULL"):
            raise ValueError(f"{symbol} trading status is {rules['status']}")

        metrics = self.client.get_metrics(self.account)
        balance = float(metrics.get("balance") or 0)
        equity = float(metrics.get("equity") or balance)
        available = float(metrics.get("availableBalance") or equity)

        step = rules["step"]
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        if quantity is None:
            budget = max_margin_usd if max_margin_usd is not None else available * SIZE_SAFETY
            notional_cap = budget / rules["margin_rate"]
            quantity = math.floor(notional_cap / ref_price / step) * step
        quantity = round(quantity, decimals)
        if quantity < rules["min_size"]:
            raise ValueError(
                f"size {quantity} below min {rules['min_size']} for {symbol} "
                f"(available ${available:,.2f}, margin rate {rules['margin_rate']})")

        sl_usd = float(sl_usd) * RISK_BUFFER
        tp_pts = float(tp_usd) / quantity
        sl_pts = sl_usd / quantity
        sign = 1 if side == "buy" else -1
        tick = 0.01
        tp_price = round(ref_price + sign * tp_pts, 2)
        sl_price = round(ref_price - sign * sl_pts, 2)
        return {
            "symbol": symbol, "side": side, "quantity": quantity,
            "ref_price": ref_price, "tp_price": tp_price, "sl_price": sl_price,
            "tp_usd": round(float(tp_usd), 2), "sl_usd": round(sl_usd, 2),
            "tp_pts": round(tp_pts, 2), "sl_pts": round(sl_pts, 2),
            "notional": round(quantity * ref_price, 2),
            "margin": round(quantity * ref_price * rules["margin_rate"], 2),
            "margin_rate": rules["margin_rate"],
            "leverage": round(1 / rules["margin_rate"], 1),
            "balance": balance, "equity": equity, "available": available,
            "tick": tick,
        }

    # ── execution ────────────────────────────────────────────────────────

    def execute(self, plan: dict, metadata: Optional[dict] = None) -> dict:
        """Place the IF-THEN bracket; returns {order_ids, position} once filled."""
        resp = self.client.place_bracket(
            self.account, instrument=plan["symbol"], side=plan["side"],
            quantity=plan["quantity"], stop_price=plan["sl_price"],
            limit_price=plan["tp_price"], metadata=metadata or {"source": "tradeops"})
        ids = [o.get("orderId") for o in (resp.get("orderResponses") or [])] \
            if isinstance(resp, dict) and "orderResponses" in resp else [resp.get("orderId")]
        positions = self.client.wait_for_position(self.account, timeout_sec=20)
        pos = None
        for p in positions:
            if str(p.get("symbol")) == plan["symbol"] and str(p.get("side")).upper() == plan["side"].upper():
                if pos is None or str(p.get("positionCode")) == str(ids[0]):
                    pos = p
        return {"order_ids": ids, "position": pos, "raw": resp}

    def enter_bracket(self, symbol: str, side: str, *, ref_price: float,
                      tp_usd: float, sl_usd: float,
                      max_margin_usd: Optional[float] = None,
                      quantity: Optional[float] = None,
                      metadata: Optional[dict] = None) -> tuple:
        plan = self.plan_bracket(symbol, side, ref_price=ref_price, tp_usd=tp_usd,
                                 sl_usd=sl_usd, max_margin_usd=max_margin_usd,
                                 quantity=quantity)
        result = self.execute(plan, metadata=metadata)
        return result, plan

    def flatten(self) -> list:
        """Market-close every open position on the account."""
        out = []
        for p in self.client.list_positions(self.account):
            close_side = "SELL" if str(p.get("side")).upper() == "BUY" else "BUY"
            try:
                out.append(self.client.close_position(
                    self.account, position_code=p["positionCode"],
                    instrument=p["symbol"], close_side=close_side))
            except DXTradeError as exc:
                out.append({"error": str(exc), "positionCode": p.get("positionCode")})
        return out
