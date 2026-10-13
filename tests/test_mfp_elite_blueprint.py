"""MyFundedPerps Elite 50K blueprint — locks the Golden Spike spec numbers."""

import pytest

from trader_companion.prop_firm_manager import PropFirmManager


@pytest.fixture
def mgr():
    return PropFirmManager()


def test_blueprint_registered_with_spec_constants(mgr):
    bp = mgr.firm_blueprints["MyFundedPerps"]
    r = bp["risk_rules"]
    assert bp["name"] == "MyFundedPerps Elite 50K"
    assert "MyFundedPerps Elite" not in mgr.firm_blueprints  # single MFP blueprint
    assert bp["execution"] == "api" and bp["asset_class"] == "perps"
    assert bp["account_sizes"] == ["$50,000"]
    assert bp["profit_split"] == 0.80
    assert r["starting_balance"] == 50000 and r["evaluation_goal"] == 55000
    assert r["static_loss_floor"] == 47500 and r["reserve"] == 50 and r["room"] == 2450
    assert r["stop_ladder"] == [1000, 1000, 450]
    assert r["funded_target_band"] == [3500, 6000]
    assert r["daily_loss_limit"] == 1500
    for alias in ("MFP Elite", "MyFundedPerps Elite", "MyFundedPerps", "MFP"):
        assert mgr.DETECTED_TO_BLUEPRINT[alias] == "MyFundedPerps"


# ── evaluation ladder: $50,000 → $55,000 ───────────────────────────────

@pytest.mark.parametrize("attempt,equity,sl,tp", [
    (0, 50000, 1000, 5000),
    (1, 49000, 1000, 6000),
    (2, 48000, 450, 7000),
])
def test_evaluation_attempts_match_spec_table(mgr, attempt, equity, sl, tp):
    p = mgr.plan_mfp_elite_attempt(equity=equity, on_funded=False, attempt_index=attempt)
    assert p["allowed"]
    assert p["sl_usd"] == sl and p["tp_usd"] == tp
    assert p["target_equity"] == 55000


def test_third_eval_stop_never_breaches_reserve(mgr):
    # 48,000 − 47,550 = 450 exactly: the ladder value and the reserve agree.
    p = mgr.plan_mfp_elite_attempt(equity=48000, on_funded=False, attempt_index=2)
    assert p["sl_usd"] == 450
    assert p["reserve_floor"] == 47550
    # If equity were lower, the stop shrinks to protect the reserve.
    p2 = mgr.plan_mfp_elite_attempt(equity=47800, on_funded=False, attempt_index=2)
    assert p2["sl_usd"] == 250


def test_fourth_attempt_retires_account(mgr):
    p = mgr.plan_mfp_elite_attempt(equity=47550, on_funded=False, attempt_index=3)
    assert not p["allowed"] and "exhausted" in p["reason"]


def test_one_attempt_per_daily_reset(mgr):
    p = mgr.plan_mfp_elite_attempt(equity=49000, on_funded=False, attempt_index=1,
                                   traded_today=True)
    assert not p["allowed"] and "daily reset" in p["reason"]


# ── funded ladder: T drawn per cycle, redrawn on restart ───────────────

def test_funded_target_is_whole_dollars_in_band_and_never_round_hundreds(mgr):
    seen = set()
    for cycle in range(200):
        T = mgr.mfp_elite_cycle_target("acct-A", cycle)
        assert 3500 <= T <= 6000
        assert T == int(T)
        assert T % 100 != 0
        seen.add(T)
    assert len(seen) > 50  # genuinely random, not a constant


def test_funded_target_is_stable_within_a_cycle_and_redrawn_per_cycle(mgr):
    t0a = mgr.mfp_elite_cycle_target("acct-B", 0)
    t0b = mgr.mfp_elite_cycle_target("acct-B", 0)
    assert t0a == t0b
    ts = {mgr.mfp_elite_cycle_target("acct-B", k) for k in range(1, 30)}
    assert len(ts) > 5


def test_funded_attempts_track_T_plus_cumulative_losses(mgr):
    mgr._account_random_state["acct-C"] = {"mfp_elite_T_cycle_0": 4000.0}
    p1 = mgr.plan_mfp_elite_attempt(equity=50000, on_funded=True, attempt_index=0,
                                    account_key="acct-C", cycle_index=0)
    p2 = mgr.plan_mfp_elite_attempt(equity=49000, on_funded=True, attempt_index=1,
                                    account_key="acct-C", cycle_index=0)
    p3 = mgr.plan_mfp_elite_attempt(equity=48000, on_funded=True, attempt_index=2,
                                    account_key="acct-C", cycle_index=0)
    assert (p1["sl_usd"], p1["tp_usd"]) == (1000, 4000)
    assert (p2["sl_usd"], p2["tp_usd"]) == (1000, 5000)
    assert (p3["sl_usd"], p3["tp_usd"]) == (450, 6000)
    assert p1["target_equity"] == 54000
    assert p1["payout_cash"] == 3200  # 80% of the $4,000 blueprint target


def test_funded_at_or_above_target_requests_payout_instead_of_trading(mgr):
    mgr._account_random_state["acct-D"] = {"mfp_elite_T_cycle_0": 4000.0}
    p = mgr.plan_mfp_elite_attempt(equity=54000, on_funded=True, attempt_index=0,
                                   account_key="acct-D", cycle_index=0)
    assert not p["allowed"] and "payout" in p["reason"]


def test_is_mfp_elite_code_variants(mgr):
    for c in ("MyFundedPerps", "MyFundedPerps Elite", "MyFundedPerps Elite 50K", "MFP Elite", "mfp_elite", "MFP"):
        assert mgr.is_mfp_elite_code(c)
    assert not mgr.is_mfp_elite_code("Tradeify247")
    assert not mgr.is_mfp_elite_code("MFFU")
