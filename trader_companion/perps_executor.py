"""MyFundedPerps bracket executor: max-size entries with $-denominated exits.

Perps PnL is size × points, so dollars-per-point equals position size. We
size every entry at the market's full leverage cap (margin = equity, less a
safety haircut for fees/slippage) and translate dollar TP/SL targets into
price distances. Bigger size means tighter point distances for the same
dollar risk — the stop never risks more than the account's remaining
daily-loss room.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from trader_companion.perps_connector import MFPClient, unwrap

# Keep margin below equity so fees/slippage can't reject the entry.
SIZE_SAFETY = 0.97
# Slice of daily-loss room reserved for fees and stop slippage.
RISK_BUFFER = 0.95
# Per-market per-user open-notional ceilings (exposure caps) are not in the
# API; discovered caps are cached here after an exposure_cap rejection.
EXPOSURE_SHRINK = 0.85
MAX_SIZING_ATTEMPTS = 6
ORDER_COOLDOWN_SEC = 1.1


class PerpsTradeExecutor:
    def __init__(self, client: MFPClient, account_id: Optional[str] = None):
        self.client = client
        self.account_id = account_id or unwrap(client.list_accounts())[0]["id"]
        self._notional_caps: dict = {}  # market_id → known-good notional ceiling

    def plan_bracket(self, market_id: str, side: str,
                     tp_usd: float, sl_usd: Optional[float] = None,
                     leverage: Optional[float] = None) -> dict:
        """Max-size plan: dollar targets → size, leverage, TP/SL prices."""
        market = unwrap(self.client.get_market(market_id))
        snap = unwrap(self.client.get_account(self.account_id))
        risk = snap["risk"]
        equity = float(risk["equity"])
        room = min(float(risk["daily_loss_room"]), float(risk["max_drawdown_room"]))

        lev = float(leverage or market["max_leverage"])
        max_risk = room * RISK_BUFFER
        sl_usd = min(float(sl_usd) if sl_usd else max_risk, max_risk)
        if sl_usd <= 0:
            raise ValueError(f"no loss room left (room={room:.2f})")

        quote = unwrap(self.client.get_quote(market_id, side=side, size=market["min_size"]))
        mid = float(quote["mid"])

        notional = equity * lev * SIZE_SAFETY
        cap = self._notional_caps.get(market_id)
        if cap:
            notional = min(notional, cap)
        step = float(market["size_step"])
        size = math.floor(notional / mid / step) * step
        size = round(size, int(market.get("size_decimals") or 8))
        if size < float(market["min_size"]):
            raise ValueError(f"equity too small for {market_id} min size")

        tp_pts = float(tp_usd) / size
        sl_pts = sl_usd / size
        sign = 1 if side == "buy" else -1
        return {
            "market_id": market_id, "side": side, "size": size,
            "leverage": lev, "mid": mid,
            "tp_price": round(mid + sign * tp_pts, 1),
            "sl_price": round(mid - sign * sl_pts, 1),
            "tp_usd": round(float(tp_usd), 2), "sl_usd": round(sl_usd, 2),
            "tp_pts": round(tp_pts, 1), "sl_pts": round(sl_pts, 1),
            "equity": equity, "loss_room": room,
        }

    def execute(self, plan: dict) -> dict:
        """Place the planned market entry with both exit legs attached."""
        order = unwrap(self.client.place_order(
            account_id=self.account_id,
            market_id=plan["market_id"], side=plan["side"], size=plan["size"],
            expected_price=plan["mid"], leverage=plan["leverage"],
            take_profit=plan["tp_price"], stop_loss=plan["sl_price"]))
        return self.client.wait_for_order(order["id"])

    def enter_bracket(self, market_id: str, side: str, tp_usd: float,
                      sl_usd: Optional[float] = None,
                      leverage: Optional[float] = None) -> tuple:
        """Plan and place at max size; on exposure_cap rejection shrink the
        notional and retry (rejections are free), caching the discovered cap."""
        for attempt in range(MAX_SIZING_ATTEMPTS):
            plan = self.plan_bracket(market_id, side, tp_usd, sl_usd=sl_usd,
                                     leverage=leverage)
            order = self.execute(plan)
            if str(order.get("status")).lower() != "rejected":
                return order, plan
            if order.get("reject_reason") != "exposure_cap":
                return order, plan
            self._notional_caps[market_id] = plan["size"] * plan["mid"] * EXPOSURE_SHRINK
            time.sleep(ORDER_COOLDOWN_SEC)
        return order, plan

    def flatten(self) -> None:
        """Close every position and cancel every working order."""
        self.client.close_all_positions(self.account_id)
        self.client.cancel_all_orders(self.account_id)
