"""Tradeify247 blueprint — published 1-Step rules and the conservative planner."""

import pytest

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp


@pytest.fixture
def mgr():
    return PropFirmManager()


def test_blueprint_registered_with_published_rules(mgr):
    bp = mgr.firm_blueprints["Tradeify247"]
    assert bp["platform"] == "DXtrade" and bp["execution"] == "api"
    assert bp["market"] == "XYZ100/USD" and bp["weekend_market"] == "BTC/USD"
    s = bp["risk_rules"]["sizes"]
    assert s[10000] == {"fee": 100.0, "profit_target": 1200.0, "daily_loss": 300.0, "max_loss": 600.0}
    assert s[25000]["daily_loss"] == 750 and s[25000]["max_loss"] == 1500
    assert s[50000]["profit_target"] == 6000 and s[100000]["max_loss"] == 6000
    assert bp["risk_rules"]["margin_rate"]["XYZ100/USD"] == 0.5
    assert bp["risk_rules"]["margin_rate"]["BTC/USD"] == 0.2
    assert mgr.DETECTED_TO_BLUEPRINT["Tradeify247"] == "Tradeify247"


@pytest.mark.parametrize("start,floor,reserve_floor,goal", [
    (10000, 9400, 9450, 11200),
    (25000, 23500, 23550, 28000),
    (50000, 47000, 47050, 56000),
    (100000, 94000, 94050, 112000),
])
def test_rules_for_balance_derive_floors(mgr, start, floor, reserve_floor, goal):
    r = mgr.tradeify247_rules_for_balance(start)
    assert r["static_loss_floor"] == floor
    assert r["reserve_floor"] == reserve_floor
    assert r["evaluation_goal"] == goal


def test_rules_for_balance_snaps_to_nearest_size(mgr):
    assert mgr.tradeify247_rules_for_balance(9999.66)["starting_balance"] == 10000
    assert mgr.tradeify247_rules_for_balance(48000)["starting_balance"] == 50000


def test_fresh_10k_eval_plan_targets_remaining_and_caps_sl_to_daily_room(mgr):
    p = mgr.plan_tradeify247_attempt(equity=10000, balance_sod=10000,
                                     starting_balance=10000, on_funded=False)
    assert p["allowed"]
    assert p["tp_usd"] == 1200
    # daily room 300, static room 550 → 300, minus $50 fee sliver
    assert p["sl_usd"] == 250
    assert p["target_equity"] == 11200


def test_sl_never_breaches_reserve_floor_near_max_loss(mgr):
    # Equity $9,500 on a 10K with today's daily room intact (SOD = equity):
    # static room = 9,500 − 9,450 = 50 → tiny stop; it can never reach the floor.
    p = mgr.plan_tradeify247_attempt(equity=9500, balance_sod=9500,
                                     starting_balance=10000, on_funded=False)
    assert p["allowed"] and p["sl_usd"] == 50
    assert 9500 - p["sl_usd"] >= 9450


def test_daily_loss_already_spent_blocks(mgr):
    # SOD 10,000, equity 9,700 → daily room 0 → not allowed (hard breach rule)
    p = mgr.plan_tradeify247_attempt(equity=9700, balance_sod=10000,
                                     starting_balance=10000, on_funded=False)
    assert not p["allowed"]


def test_at_target_requests_payout(mgr):
    p = mgr.plan_tradeify247_attempt(equity=11200, balance_sod=11000,
                                     starting_balance=10000, on_funded=False)
    assert not p["allowed"] and "payout" in p["reason"]


def test_funded_uses_custom_target_when_given(mgr):
    p = mgr.plan_tradeify247_attempt(equity=10000, balance_sod=10000,
                                     starting_balance=10000, on_funded=True,
                                     target_profit=800)
    assert p["tp_usd"] == 800


def test_starting_balance_from_account_id():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    assert app._tradeify247_starting_balance({"acct_num": "1S10K2166973"}, 0) == 10000
    assert app._tradeify247_starting_balance({"acct_num": "2S50K1"}, 0) == 50000
    assert app._tradeify247_starting_balance({"acct_num": "IF25K9"}, 0) == 25000
    assert app._tradeify247_starting_balance({"acct_num": "x", "eval": {"Account Size": "$100,000"}}, 0) == 100000
    assert app._tradeify247_starting_balance({"acct_num": "x", "eval": {}}, 9999.66) == 9999.66
