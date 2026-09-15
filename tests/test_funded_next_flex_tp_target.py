from trader_companion.prop_firm_manager import PropFirmManager


def test_calculate_adjusted_tp_can_target_funded_next_flex_3050_goal():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 14,
        "tradovate_tp_ticks": 150,
        "tradovate_sl_ticks": 150,
        "mt5_tp_points": 35,
        "mt5_sl_points": 35,
    }

    adjusted = manager.calculate_adjusted_tp(
        config,
        stage_profit_so_far=1000.0,
        tick_value=5.0,
        target_profit_dollars=3050.0,
    )

    assert adjusted["tradovate_tp_ticks"] == 29


def test_tradeify_select_randomization_keeps_ft1_and_farm_sl_in_ranges():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
        "mt5_tp_points": 0,
        "mt5_sl_points": 0,
    }

    result = manager.randomize_trade_config(
        firm_code="Tradeify Select",
        phase_key="funded_trade1",
        config=config,
        account_key="acct-1",
        balance=50000.0,
    )

    assert 54500 <= 50000 + (result["tradovate_tp_ticks"] * 10) <= 56000 or result["tradovate_tp_ticks"] >= 500
    assert 450 <= result["tradovate_sl_ticks"] <= 600 or result["tradovate_sl_ticks"] == 200


def test_ftmo_pro_farm_sl_uses_account_base_and_jitter_bounds():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "MNQU6",
        "tradovate_qty": 1,
        "tradovate_tp_ticks": 31,
        "tradovate_sl_ticks": 200,
    }

    result = manager.randomize_trade_config(
        firm_code="FTMO Futures Pro",
        phase_key="farming",
        config=config,
        account_key="acct-2",
        balance=54000.0,
    )

    assert 480 <= result["tradovate_sl_ticks"] <= 600


def test_remaining_prop_firms_use_stable_farming_randomization():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 1,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 150,
    }
    remaining_firms = (
        "MFFU_Flex", "Funded Next", "FundingTicks", "TopStep", "TopStep RTP",
        "TradeDay", "AlphaFutures", "Tradeify", "Apex",
        "Top One Futures", "The5ers", "Funded Futures Family", "GoatFunded",
        "Funded Next Flex", "FTMO Futures",
    )

    for firm in remaining_firms:
        first = manager.randomize_trade_config(
            firm, "farming", config, account_key=f"{firm}-account")
        second = manager.randomize_trade_config(
            firm, "farming", config, account_key=f"{firm}-account")

        assert first["_randomization"]["policy"] == "generic_per_account"
        assert second["tradovate_tp_ticks"] == first["tradovate_tp_ticks"]
        assert second["tradovate_sl_ticks"] == first["tradovate_sl_ticks"]
        assert config["tradovate_tp_ticks"] == 200
        assert config["tradovate_sl_ticks"] == 150


def test_rapid_daily_funded_randomization_uses_spec_rules():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "MNQU6",
        "tradovate_qty": 4,
        "tradovate_tp_ticks": 400,
        "tradovate_sl_ticks": 100,
    }

    challenge = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "challenge_trade1", config,
        account_key="rapid-account", balance=50000.0)
    assert challenge == config

    ft1 = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade1", config,
        account_key="rapid-account", balance=50000.0)
    ft1_repeat = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade1_recovery", config,
        account_key="rapid-account", balance=50000.0)
    target_ticks = ft1["_randomization"]["target_ticks"]
    assert 400 <= target_ticks <= 500
    assert ft1["tradovate_tp_ticks"] == target_ticks
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_symbol"] == "NQU6"
    assert ft1["tradovate_qty"] == 2
    assert ft1["tradovate_sl_ticks"] == 100

    ft2 = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade2", config,
        account_key="rapid-account", balance=53200.0)
    assert 400 <= ft2["tradovate_tp_ticks"] <= 500
    assert ft2["tradovate_sl_ticks"] == 100

    floor_case = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade2", config,
        account_key="rapid-account-2", balance=53500.0)
    assert 400 <= floor_case["tradovate_tp_ticks"] <= 500


def test_rapid_daily_blueprint_uses_two_nq_funded_cycle_one_setup():
    manager = PropFirmManager()

    trade1 = manager.get_strategy_config(
        "FundedNext Rapid Daily", "funded_trade1", "50k")
    recovery = manager.get_strategy_config(
        "FundedNext Rapid Daily", "funded_trade1_recovery", "50k")
    rules = manager.get_firm_info("FundedNext Rapid Daily")["rules"]

    assert trade1["tradovate_symbol"] == "NQU6"
    assert trade1["tradovate_qty"] == 2
    assert trade1["tradovate_tp_ticks"] == 400
    assert trade1["tradovate_sl_ticks"] == 100
    assert recovery["tradovate_symbol"] == "NQU6"
    assert recovery["tradovate_qty"] == 2
    assert recovery["tradovate_tp_ticks"] == 500
    assert recovery["tradovate_sl_ticks"] == 100
    assert rules["payout_request_gross"] == 1200
    assert rules["payout_receive_before_provider_fees"] == 1080
    assert rules["payout1_retained_balance"] == 52800


def test_blue_guardian_reserve_ft2_plus_uses_live_balance_auto_adjustment():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    }

    balance = 53200.0
    result = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade2", config,
        account_key="bgr-account", balance=balance)
    target = result["_randomization"]["target_dollars"]

    assert 53500 <= target <= 55000
    assert result["tradovate_tp_ticks"] == max(80, min(600, int((target - balance) // 10)))
    assert result["tradovate_sl_ticks"] == 310

    floor_result = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade3", config,
        account_key="bgr-floor", balance=54000.0)
    assert floor_result["tradovate_tp_ticks"] >= 80
    assert floor_result["tradovate_sl_ticks"] == 390

    high_balance = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade5", config,
        account_key="bgr-high", balance=60000.0)
    assert high_balance["tradovate_tp_ticks"] == 80
    assert high_balance["tradovate_sl_ticks"] == 600


def test_lucid_flex_50k_uses_randomization_spec():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 140,
        "tradovate_sl_ticks": 200,
    }

    ft1 = manager.randomize_trade_config(
        "Lucid", "funded_trade1", config,
        account_key="lucid-account", balance=50000.0)
    ft1_repeat = manager.randomize_trade_config(
        "Lucid", "funded_trade1_recovery", config,
        account_key="lucid-account", balance=50000.0)
    target = ft1["_randomization"]["target_dollars"]
    assert 53000 <= target <= 54000
    assert ft1["tradovate_qty"] == 2
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_sl_ticks"] == 200

    ft2 = manager.randomize_trade_config(
        "Lucid", "funded_trade2", config,
        account_key="lucid-account", balance=53200.0)
    ft2_target = ft2["_randomization"]["target_dollars"]
    assert 1300 <= ft2["_randomization"]["offset_dollars"] <= 1700
    assert ft2["tradovate_tp_ticks"] == max(
        0, min(600, int((ft2_target - 53200.0 + 17.0) // 10)))
    assert ft2["tradovate_sl_ticks"] == 310

    farm = manager.randomize_trade_config(
        "Lucid", "farming", config,
        account_key="lucid-account", balance=54000.0)
    assert farm["tradovate_qty"] == 2
    assert farm["tradovate_symbol"] == "MNQU6"
    assert farm["tradovate_tp_ticks"] == 156
    assert 450 <= farm["tradovate_sl_ticks"] <= 600


def test_mffu_rapid_eod_uses_spec_ranges_and_fixed_stops():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 3,
        "tradovate_tp_ticks": 267,
        "tradovate_sl_ticks": 133,
    }

    ft1 = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade1", config,
        account_key="mffu-eod", balance=50000.0)
    ft1_repeat = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade1_recovery", config,
        account_key="mffu-eod", balance=50000.0)
    assert 305 <= ft1["tradovate_tp_ticks"] <= 335
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_sl_ticks"] == 133

    ft2 = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade2", config,
        account_key="mffu-eod", balance=54500.0)
    assert 267 <= ft2["tradovate_tp_ticks"] <= 450
    assert ft2["tradovate_tp_ticks"] not in (300, 400)
    assert ft2["tradovate_sl_ticks"] == 133

    challenge = manager.randomize_trade_config(
        "MFFU Rapid EOD", "challenge_trade1", config,
        account_key="mffu-eod", balance=50000.0)
    assert challenge["tradovate_tp_ticks"] == 51
    assert challenge["tradovate_sl_ticks"] == 133


def test_topstep_xfa_uses_spec_ranges_and_fixed_stops():
    manager = PropFirmManager()
    config = {
        "topstepx_symbol": "NQU26",
        "topstepx_qty": 2,
        "topstepx_tp_ticks": 400,
        "topstepx_sl_ticks": 200,
    }

    ft1 = manager.randomize_trade_config(
        "TopStep 50K XFA", "funded_trade1", config,
        account_key="xfa-account", balance=0.0)
    ft1_repeat = manager.randomize_trade_config(
        "TopStep XFA", "funded_trade1_recovery", config,
        account_key="xfa-account", balance=0.0)
    assert 401 <= ft1["topstepx_tp_ticks"] <= 501
    assert ft1["topstepx_tp_ticks"] == ft1_repeat["topstepx_tp_ticks"]
    assert ft1["topstepx_sl_ticks"] == 200

    ft2 = manager.randomize_trade_config(
        "TopStep 50K XFA", "funded_trade2", config,
        account_key="xfa-account", balance=2000.0)
    assert 199 <= ft2["topstepx_tp_ticks"] <= 499
    assert ft2["topstepx_sl_ticks"] == 200
    assert ft2["topstepx_tp_ticks"] not in (300, 400)

    challenge = manager.randomize_trade_config(
        "TopStep 50K XFA", "challenge_trade1", config,
        account_key="xfa-account", balance=0.0)
    assert challenge["topstepx_tp_ticks"] == 152
    assert challenge["topstepx_sl_ticks"] == 200
