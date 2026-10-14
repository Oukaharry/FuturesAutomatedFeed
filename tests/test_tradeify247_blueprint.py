"""Tradeify247 blueprint — Standard 1-Step $50K spec + randomization (scaled per size)."""

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
    rr = bp["risk_rules"]
    s = rr["sizes"]
    assert s[10000] == {"fee": 100.0, "profit_target": 1200.0, "daily_loss": 300.0, "max_loss": 600.0}
    assert s[25000]["daily_loss"] == 750 and s[25000]["max_loss"] == 1500
    assert s[50000]["profit_target"] == 6000 and s[100000]["max_loss"] == 6000
    assert rr["margin_rate"]["XYZ100/USD"] == 0.5 and rr["margin_rate"]["BTC/USD"] == 0.2
    assert rr["risk_1"] == 1450 and rr["risk_2"] == 1500 and rr["trade_cost"] == 200
    assert rr["funded_target_band"] == [3500, 6000] and rr["max_attempts"] == 2
    assert rr["daily_loss_fixed"] and rr["min_hold_seconds"] == 20
    assert mgr.DETECTED_TO_BLUEPRINT["Tradeify247"] == "Tradeify247"


@pytest.mark.parametrize("start,floor,goal,risk1,risk2,cost", [
    (10000, 9400, 11200, 290, 300, 40),
    (25000, 23500, 28000, 725, 750, 100),
    (50000, 47000, 56000, 1450, 1500, 200),
    (100000, 94000, 112000, 2900, 3000, 400),
])
def test_rules_for_balance_scale_the_50k_spec(mgr, start, floor, goal, risk1, risk2, cost):
    r = mgr.tradeify247_rules_for_balance(start)
    assert r["static_loss_floor"] == floor and r["reserve_floor"] == floor
    assert r["evaluation_goal"] == goal
    assert r["risk_1"] == risk1 and r["risk_2"] == risk2 and r["trade_cost"] == cost


def test_rules_for_balance_snaps_to_nearest_size(mgr):
    assert mgr.tradeify247_rules_for_balance(9999.66)["starting_balance"] == 10000
    assert mgr.tradeify247_rules_for_balance(48000)["starting_balance"] == 50000


def test_eval_attempt1_50k_matches_blueprint(mgr):
    p = mgr.plan_tradeify247_attempt(equity=50000, balance_sod=50000, starting_balance=50000, on_funded=False)
    # all-in $1,450 → price stop $1,250; net goal $6,000 → price target $6,200
    assert p["allowed"] and p["attempt"] == 1
    assert p["risk_budget"] == 1450 and p["sl_usd"] == 1250 and p["tp_usd"] == 6200
    assert p["target_equity"] == 56000


def test_eval_attempt2_50k_full_dll_and_target_grows_by_loss(mgr):
    p = mgr.plan_tradeify247_attempt(equity=48550, balance_sod=48550, starting_balance=50000,
                                     on_funded=False, attempt_index=1)
    assert p["allowed"] and p["risk_budget"] == 1500 and p["sl_usd"] == 1300 and p["tp_usd"] == 7650


def test_fresh_10k_eval_plan_is_the_scaled_spec(mgr):
    p = mgr.plan_tradeify247_attempt(equity=10000, balance_sod=10000, starting_balance=10000, on_funded=False)
    assert p["allowed"] and p["risk_budget"] == 290 and p["sl_usd"] == 250 and p["tp_usd"] == 1240
    assert p["target_equity"] == 11200


def test_budget_never_breaches_static_floor(mgr):
    # Equity $9,500 on a 10K: static room = 100 → budget 100, price stop 60 after $40 cost.
    p = mgr.plan_tradeify247_attempt(equity=9500, balance_sod=9500, starting_balance=10000, on_funded=False)
    assert p["allowed"] and p["risk_budget"] == 100 and p["sl_usd"] == 60
    assert 9500 - p["risk_budget"] >= 9400


def test_daily_loss_already_spent_blocks(mgr):
    # SOD 10,000, equity 9,700 → daily room 0 → not allowed (hard breach rule)
    p = mgr.plan_tradeify247_attempt(equity=9700, balance_sod=10000, starting_balance=10000, on_funded=False)
    assert not p["allowed"]


def test_at_target_requests_payout(mgr):
    p = mgr.plan_tradeify247_attempt(equity=11200, balance_sod=11000, starting_balance=10000, on_funded=False)
    assert not p["allowed"] and "payout" in p["reason"]


def test_blocks_third_attempt_and_same_window_repeat(mgr):
    assert "retired" in mgr.plan_tradeify247_attempt(equity=47050, balance_sod=47050, starting_balance=50000,
                                                     on_funded=False, attempt_index=2)["reason"]
    assert "22:00 UTC" in mgr.plan_tradeify247_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                                       on_funded=False, traded_today=True)["reason"]


def test_funded_T_random_per_cycle_and_brackets(mgr):
    seen = set()
    for i in range(300):
        T = mgr.tradeify247_cycle_target("a", i)
        assert 3500 <= T <= 6000 and T == int(T) and T % 100 != 0
        seen.add(T)
    assert len(seen) > 100
    T0 = mgr.tradeify247_cycle_target("a", 0)
    p = mgr.plan_tradeify247_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                     on_funded=True, account_key="a", cycle_index=0)
    assert p["T"] == T0 and p["sl_usd"] == 1250 and p["tp_usd"] == T0 + 200
    assert p["payout_cash"] == pytest.approx(0.8 * T0)
    p2 = mgr.plan_tradeify247_attempt(equity=48550, balance_sod=48550, starting_balance=50000,
                                      on_funded=True, account_key="a", cycle_index=0, attempt_index=1)
    assert p2["T"] == T0 and p2["sl_usd"] == 1300 and p2["tp_usd"] == T0 + 1450 + 200


def test_funded_uses_custom_target_and_measured_cost_when_given(mgr):
    p = mgr.plan_tradeify247_attempt(equity=10000, balance_sod=10000, starting_balance=10000,
                                     on_funded=True, target_profit=800, trade_cost=25)
    assert p["T"] == 800 and p["tp_usd"] == 825 and p["sl_usd"] == 265


def test_starting_balance_from_account_id():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    assert app._tradeify247_starting_balance({"acct_num": "1S10K2166973"}, 0) == 10000
    assert app._tradeify247_starting_balance({"acct_num": "2S50K1"}, 0) == 50000
    assert app._tradeify247_starting_balance({"acct_num": "IF25K9"}, 0) == 25000
    assert app._tradeify247_starting_balance({"acct_num": "x", "eval": {"Account Size": "$100,000"}}, 0) == 100000
    assert app._tradeify247_starting_balance({"acct_num": "x", "eval": {}}, 9999.66) == 9999.66
