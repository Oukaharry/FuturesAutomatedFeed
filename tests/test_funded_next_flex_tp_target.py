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
