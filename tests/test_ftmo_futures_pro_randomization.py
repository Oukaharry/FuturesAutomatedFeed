import random

from trader_companion.prop_firm_manager import PropFirmManager


def _nq_config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 95,
    }


def _mnq_config():
    return {
        "tradovate_symbol": "MNQU6",
        "tradovate_qty": 3,
        "tradovate_tp_ticks": 138,
        "tradovate_sl_ticks": 500,
    }


def test_ftmo_pro_first_cycle_uses_live_balance_adjustments():
    random.seed(20260915)
    manager = PropFirmManager()
    account = "ftmo-cycle-001"

    ft1 = manager.randomize_trade_config(
        "FTMO Futures Pro", "funded_trade1", _nq_config(),
        account_key=account, balance=50000.0)
    assert 500 <= ft1["tradovate_tp_ticks"] <= 600
    assert ft1["tradovate_sl_ticks"] == 95

    balance = 50000.0 + ft1["tradovate_tp_ticks"] * 10.0
    for day in range(4):
        farm = manager.randomize_trade_config(
            "FTMO Futures Pro", "farming", _mnq_config(),
            account_key=account, balance=balance)
        assert farm["tradovate_tp_ticks"] == 138
        assert 480 <= farm["tradovate_sl_ticks"] <= 600
        balance += 138 * 1.5

    ft2 = manager.randomize_trade_config(
        "FTMO Futures Pro", "funded_trade2", _nq_config(),
        account_key=account, balance=balance)
    assert 0 <= ft2["tradovate_tp_ticks"] <= 600
    assert ft2["tradovate_sl_ticks"] == min(
        95, int((balance - 50050.0) // 10))
    assert ft2["_randomization"]["draw"] == "FT2_PLUS_TARGET_BALANCE"


def test_ftmo_pro_ft1_tp_and_farm_base_are_unique_across_accounts():
    random.seed(20260915)
    manager = PropFirmManager()
    tps = set()
    farm_bases = set()
    for number in range(20):
        account = f"ftmo-unique-{number:03d}"
        ft1 = manager.randomize_trade_config(
            "FTMO Futures Pro", "funded_trade1", _nq_config(),
            account_key=account, balance=50000.0)
        farm = manager.randomize_trade_config(
            "FTMO Futures Pro", "farming", _mnq_config(),
            account_key=account, balance=56000.0)
        tps.add(ft1["tradovate_tp_ticks"])
        farm_bases.add(farm["_randomization"]["farm_sl_base"])

    assert len(tps) == 20
    assert all(500 <= tp <= 600 for tp in tps)
    assert len(farm_bases) == 20
    assert all(500 <= base <= 580 for base in farm_bases)
