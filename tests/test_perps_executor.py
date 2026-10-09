"""Perps executor: max-size planning, risk clamps, exposure-cap retry."""

from unittest.mock import MagicMock

import pytest

from trader_companion.perps_executor import PerpsTradeExecutor


def _client(equity=100000, daily_room=4000, dd_room=6000, mid=31000,
            max_leverage=12):
    c = MagicMock()
    c.list_accounts.return_value = {"data": [{"id": "a1"}]}
    c.get_account.return_value = {"data": {
        "starting_balance": 100000,
        "risk": {"equity": equity, "daily_loss_room": daily_room,
                 "max_drawdown_room": dd_room}}}
    c.get_market.return_value = {"data": {
        "market_id": "hyperliquid|xyz:XYZ100", "max_leverage": max_leverage,
        "min_size": 0.0001, "size_step": 0.0001, "size_decimals": 4}}
    c.get_quote.return_value = {"data": {"mid": mid}}
    return c


def test_plan_sizes_at_max_leverage_with_safety():
    ex = PerpsTradeExecutor(_client())
    plan = ex.plan_bracket("hyperliquid|xyz:XYZ100", "buy", tp_usd=8000)
    assert plan["leverage"] == 12
    # size*mid ≈ equity*12*0.97
    assert plan["size"] * plan["mid"] == pytest.approx(100000 * 12 * 0.97, rel=0.001)
    # dollar targets honored: size × pts == usd
    assert plan["size"] * plan["tp_pts"] == pytest.approx(8000, rel=0.01)
    assert plan["tp_price"] > plan["mid"] > plan["sl_price"]


def test_sl_clamped_to_loss_room():
    ex = PerpsTradeExecutor(_client(daily_room=2000, dd_room=5000))
    plan = ex.plan_bracket("hyperliquid|xyz:XYZ100", "buy",
                           tp_usd=8000, sl_usd=999999)
    assert plan["sl_usd"] == pytest.approx(2000 * 0.95)


def test_short_side_flips_bracket():
    ex = PerpsTradeExecutor(_client())
    plan = ex.plan_bracket("hyperliquid|xyz:XYZ100", "sell", tp_usd=8000)
    assert plan["tp_price"] < plan["mid"] < plan["sl_price"]


def test_no_loss_room_raises():
    ex = PerpsTradeExecutor(_client(daily_room=0))
    with pytest.raises(ValueError):
        ex.plan_bracket("hyperliquid|xyz:XYZ100", "buy", tp_usd=8000)


def test_exposure_cap_rejection_shrinks_and_retries(monkeypatch):
    c = _client()
    ex = PerpsTradeExecutor(c)
    results = [{"status": "rejected", "reject_reason": "exposure_cap"},
               {"status": "filled", "fill_price": 31000}]
    monkeypatch.setattr(ex, "execute", lambda plan: results.pop(0))
    monkeypatch.setattr("time.sleep", lambda s: None)
    order, plan = ex.enter_bracket("hyperliquid|xyz:XYZ100", "buy", tp_usd=8000)
    assert order["status"] == "filled"
    # second plan sized under the cached cap (first notional × 0.85)
    first_notional = 100000 * 12 * 0.97
    assert plan["size"] * plan["mid"] <= first_notional * 0.85 * 1.001


def test_non_exposure_rejection_does_not_retry(monkeypatch):
    ex = PerpsTradeExecutor(_client())
    calls = []
    monkeypatch.setattr(ex, "execute", lambda plan: calls.append(1) or
                        {"status": "rejected", "reject_reason": "insufficient_margin"})
    order, _ = ex.enter_bracket("hyperliquid|xyz:XYZ100", "buy", tp_usd=8000)
    assert order["reject_reason"] == "insufficient_margin"
    assert len(calls) == 1
