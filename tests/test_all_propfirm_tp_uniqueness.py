import random

from trader_companion.prop_firm_manager import PropFirmManager


CONFIGS = {
    "Tradeify Select": {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    },
    "MFFU_Flex": {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    },
    "Funded Next": {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    },
    "TopStep RTP": {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    },
    "Lucid": {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    },
}


def test_fundednext_rapid_daily_ft1_cap_is_shared_by_design():
    random.seed(20260915)
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 300,
        "tradovate_sl_ticks": 496,
    }
    first = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade1", config,
        account_key="fundednext-001", balance=50000.0)
    second = manager.randomize_trade_config(
        "FundedNext Rapid Daily", "funded_trade1", config,
        account_key="fundednext-002", balance=50000.0)

    assert first["tradovate_tp_ticks"] == 600
    assert second["tradovate_tp_ticks"] == 600


def test_ftmo_futures_pro_ft1_floor_is_shared_by_current_rule():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 95,
    }
    first = manager.randomize_trade_config(
        "FTMO Futures Pro", "funded_trade1", config,
        account_key="ftmo-001", balance=50000.0)
    second = manager.randomize_trade_config(
        "FTMO Futures Pro", "funded_trade1", config,
        account_key="ftmo-002", balance=50000.0)

    assert 500 <= first["tradovate_tp_ticks"] <= 600
    assert 500 <= second["tradovate_tp_ticks"] <= 600
    assert first["tradovate_tp_ticks"] != second["tradovate_tp_ticks"]


def test_every_randomized_funded_family_has_no_cross_account_tp_reuse():
    random.seed(20260915)
    for firm, config in CONFIGS.items():
        manager = PropFirmManager()
        owners = {}
        for account_number in range(1, 21):
            account_id = f"{firm}-{account_number:03d}"
            for trade_number in (1, 2):
                result = manager.randomize_trade_config(
                    firm,
                    f"funded_trade{trade_number}",
                    config,
                    account_key=account_id,
                    balance=50000.0,
                )
                tp_key = "tradovate_tp_ticks"
                if tp_key not in result:
                    tp_key = "topstepx_tp_ticks"
                tp = result[tp_key]
                owner = owners.setdefault(tp, account_id)
                assert owner == account_id, (firm, tp, owner, account_id)


def test_existing_account_can_reuse_its_own_funded_tp():
    random.seed(20260915)
    manager = PropFirmManager()
    config = CONFIGS["Lucid"]
    first = manager.randomize_trade_config(
        "Lucid", "funded_trade1", config,
        account_key="same-account", balance=50000.0)
    second = manager.randomize_trade_config(
        "Lucid", "funded_trade1_recovery", config,
        account_key="same-account", balance=50000.0)

    assert first["tradovate_tp_ticks"] == second["tradovate_tp_ticks"]
