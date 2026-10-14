"""Breakout Classic $50K blueprint + randomization spec tests (no network)."""

import pytest

from trader_companion.prop_firm_manager import PropFirmManager

ACCT = "W3M6-SHMX-Y67Z-MELW"
USD = lambda a: {"amount": f"{a:.4f}", "asset": {"name": "USD", "class": "currency"}}
LIVE50 = {"plan": {"initial_size": USD(50000), "target_equity_value": USD(55000),
                   "max_drawdown_equity_value": USD(47000), "max_daily_loss_equity_value": USD(48500)}}
# The real Turbo Eval $5K seen live: both floors at 4,850, target 5,450.
LIVE_TURBO5K = {"plan": {"initial_size": USD(5000), "target_equity_value": USD(5450),
                         "max_drawdown_equity_value": USD(4850), "max_daily_loss_equity_value": USD(4850)}}


def test_blueprint_constants():
    bp = PropFirmManager().firm_blueprints["Breakout"]
    rr = bp["risk_rules"]
    assert bp["market"] == "XYZ100/USD" and bp["profit_split"] == 0.8 and bp["purchase_fee"] == 400
    assert rr["starting_balance"] == 50000 and rr["evaluation_goal"] == 55000 and rr["static_loss_floor"] == 47000
    assert rr["risk_1"] == 1450 and rr["risk_2_pct"] == 0.03 and rr["trade_cost"] == 200
    assert rr["funded_target_band"] == [3500, 6000] and rr["max_attempts"] == 2


@pytest.mark.parametrize("acct", [ACCT, "W3M6 SHMX Y67Z MELW", "aa06-n84g-j2zq-wyri"])
def test_detects_breakout_account_ids(acct):
    assert PropFirmManager().detect_prop_firm(acct) == "Breakout"


@pytest.mark.parametrize("acct", ["875c7864-2672-5a3f-890b-a9f594ef1c32", "1S10K2166973", "TDFYSL50469269857", "ABC-DEFG-HIJK-LMNO"])
def test_breakout_detection_does_not_steal_others(acct):
    assert PropFirmManager().detect_prop_firm(acct) != "Breakout"


def test_rules_from_live_record():
    r = PropFirmManager().breakout_rules_for_balance(50000, live=LIVE50)
    assert r["evaluation_goal"] == 55000 and r["static_loss_floor"] == 47000 and r["daily_loss_floor"] == 48500
    assert r["risk_1"] == 1450 and r["trade_cost"] == 200 and r["scale"] == 1.0


def test_eval_attempt1_brackets_match_blueprint():
    p = PropFirmManager().plan_breakout_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                                on_funded=False, live=LIVE50, attempt_index=0)
    # all-in $1,450 → price stop $1,250; net goal $5,000 → price target $5,200
    assert p["allowed"] and p["risk_budget"] == 1450 and p["sl_usd"] == 1250 and p["tp_usd"] == 5200


def test_eval_attempt2_uses_3pct_of_reset_and_grows_target_by_loss():
    live = {"plan": dict(LIVE50["plan"], max_daily_loss_equity_value=USD(48550 - 1456.5))}
    p = PropFirmManager().plan_breakout_attempt(equity=48550, balance_sod=48550, starting_balance=50000,
                                                on_funded=False, live=live, attempt_index=1)
    assert p["allowed"] and p["risk_budget"] == 1456.5 and p["sl_usd"] == 1256.5 and p["tp_usd"] == 6650


def test_funded_brackets_use_T_plus_cost():
    m = PropFirmManager()
    T = m.breakout_cycle_target("a", 0)
    p = m.plan_breakout_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                on_funded=True, live=LIVE50, account_key="a", cycle_index=0)
    assert p["T"] == T and p["sl_usd"] == 1250 and p["tp_usd"] == T + 200
    assert p["payout_cash"] == pytest.approx(0.8 * T)
    live2 = {"plan": dict(LIVE50["plan"], max_daily_loss_equity_value=USD(48550 - 1456.5))}
    p2 = m.plan_breakout_attempt(equity=48550, balance_sod=48550, starting_balance=50000,
                                 on_funded=True, live=live2, account_key="a", cycle_index=0, attempt_index=1)
    assert p2["T"] == T and p2["sl_usd"] == 1256.5 and p2["tp_usd"] == T + 1450 + 200


def test_T_draw_band_whole_dollars_no_hundreds_and_redraw_per_cycle():
    m = PropFirmManager()
    seen = set()
    for i in range(300):
        T = m.breakout_cycle_target("x", i)
        assert 3500 <= T <= 6000 and T == int(T) and T % 100 != 0
        seen.add(T)
    assert len(seen) > 100
    assert m.breakout_cycle_target("x", 0) == m.breakout_cycle_target("x", 0)


def test_measured_cost_override_and_blocks():
    m = PropFirmManager()
    p = m.plan_breakout_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                on_funded=False, live=LIVE50, trade_cost=120)
    assert p["sl_usd"] == 1330 and p["tp_usd"] == 5120
    assert "retired" in m.plan_breakout_attempt(equity=47093.5, balance_sod=47093.5, starting_balance=50000,
                                                on_funded=False, live=LIVE50, attempt_index=2)["reason"]
    assert "00:30 UTC" in m.plan_breakout_attempt(equity=50000, balance_sod=50000, starting_balance=50000,
                                                  on_funded=False, live=LIVE50, traded_today=True)["reason"]
    assert not m.plan_breakout_attempt(equity=55000, balance_sod=55000, starting_balance=50000,
                                       on_funded=False, live=LIVE50)["allowed"]


def test_turbo_5k_live_floors_cap_the_budget():
    # Turbo signature (DLL == MDD) → Turbo blueprint: single attempt, $145 all-in, $20 cost.
    live = {"name": "Turbo Eval 1", "plan": dict(LIVE_TURBO5K["plan"],
                                                  max_daily_drawdown_value=USD(150), max_drawdown_value=USD(150))}
    m = PropFirmManager()
    assert m.breakout_plan_kind(live) == "turbo" and m.breakout_plan_kind(LIVE50) == "classic"
    assert m.breakout_plan_kind(None, "Breakout Turbo") == "turbo"
    p = m.plan_breakout_attempt(equity=5000, balance_sod=5000, starting_balance=5000,
                                on_funded=False, live=live)
    assert p["allowed"] and p["kind"] == "turbo" and p["blueprint"] == "Breakout Turbo"
    assert p["risk_budget"] == 145 and p["sl_usd"] == 125 and p["tp_usd"] == 470 and p["target_equity"] == 5450
    # a second attempt is refused outright on Turbo
    p2 = m.plan_breakout_attempt(equity=4855, balance_sod=4855, starting_balance=5000,
                                 on_funded=False, live=live, attempt_index=1)
    assert not p2["allowed"] and "Turbo" in p2["reason"]


def test_turbo_blueprint_constants_and_funded_band():
    m = PropFirmManager()
    bp = m.firm_blueprints["Breakout Turbo"]
    rr = bp["risk_rules"]
    assert bp["account_sizes"] == ["$5,000"] and rr["evaluation_goal"] == 5450 and rr["static_loss_floor"] == 4850
    assert rr["risk_1"] == 145 and rr["trade_cost"] == 20 and rr["max_attempts"] == 1
    assert m.DETECTED_TO_BLUEPRINT["Breakout Turbo"] == "Breakout Turbo"
    seen = set()
    for i in range(200):
        T = m.breakout_cycle_target("t", i, kind="turbo")
        assert 350 <= T <= 600 and T == int(T) and T % 100 != 0
        seen.add(T)
    assert len(seen) > 50
    p = m.plan_breakout_attempt(equity=5000, balance_sod=5000, starting_balance=5000, on_funded=True,
                                live={"name": "Turbo Eval 1", "plan": LIVE_TURBO5K["plan"]},
                                account_key="t", cycle_index=0)
    assert 350 <= p["T"] <= 600 and p["sl_usd"] == 125 and p["tp_usd"] == p["T"] + 20


def test_classic_5k_without_turbo_signature_keeps_two_attempts():
    # A $5K Classic (DLL 3% vs MDD 6%) still scales the Classic ladder.
    live = {"plan": {"initial_size": USD(5000), "target_equity_value": USD(5500),
                     "max_drawdown_equity_value": USD(4700), "max_daily_loss_equity_value": USD(4850),
                     "max_daily_drawdown_value": USD(150), "max_drawdown_value": USD(300)}}
    m = PropFirmManager()
    assert m.breakout_plan_kind(live) == "classic"
    p = m.plan_breakout_attempt(equity=5000, balance_sod=5000, starting_balance=5000, on_funded=False, live=live)
    assert p["kind"] == "classic" and p["risk_budget"] == 145 and p["tp_usd"] == 520
