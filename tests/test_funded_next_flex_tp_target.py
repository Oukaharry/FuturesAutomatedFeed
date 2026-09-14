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

    assert 100 <= result["tradovate_sl_ticks"] <= 390


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
        "Lucid", "TradeDay", "AlphaFutures", "Tradeify", "Apex",
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
    assert 27325 <= target_ticks < 27625
    assert ft1["tradovate_tp_ticks"] == 600
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_sl_ticks"] == 496

    ft2 = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade2", config,
        account_key="rapid-account", balance=53200.0)
    assert ft2["tradovate_tp_ticks"] == 131
    assert ft2["tradovate_sl_ticks"] == 496

    floor_case = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade2", config,
        account_key="rapid-account-2", balance=53500.0)
    assert floor_case["tradovate_tp_ticks"] == 131
