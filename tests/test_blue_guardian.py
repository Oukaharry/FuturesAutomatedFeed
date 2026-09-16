import json

from trader_companion.prop_firm_manager import PropFirmManager
from tests.simulate_blue_guardian import run_simulation


def _config():
    return {
        "tradovate_symbol": "NQZ6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    }


def test_blue_guardian_effective_tp_applies_minimum_and_reaches_far_targets(monkeypatch):
    manager = PropFirmManager()
    balance = 52805.0

    monkeypatch.setattr(manager, "_draw_uniform", lambda low, high: 53515.156)
    minimum_case = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade2", _config(),
        account_key="bgr-minimum", balance=balance)

    assert minimum_case["tradovate_tp_ticks"] == 80
    assert minimum_case["tradovate_sl_ticks"] == 270

    monkeypatch.setattr(manager, "_draw_uniform", lambda low, high: 55000.0)
    farther_target_case = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade2", _config(),
        account_key="bgr-farther-target", balance=balance)

    assert farther_target_case["tradovate_tp_ticks"] == 219
    assert farther_target_case["tradovate_tp_ticks"] > 80


def test_blue_guardian_eval_and_ft1_persist_per_account(monkeypatch):
    manager = PropFirmManager()
    monkeypatch.setattr(
        "trader_companion.prop_firm_manager.random.choice",
        lambda _choices: ("MNQZ6", 20, 2))
    draws = iter((304.0, 300.0, 54250.0))
    monkeypatch.setattr(manager, "_draw_uniform", lambda _low, _high: next(draws))

    eval_day1 = manager.randomize_trade_config(
        "Blue Guardian Reserve", "challenge_trade1", _config(), account_key="BGR-001")
    eval_day2 = manager.randomize_trade_config(
        "Blue Guardian Reserve", "challenge_trade2", _config(), account_key="BGR-001")
    ft1 = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade1", _config(), account_key="BGR-001")
    ft1_repeat = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade1_recovery", _config(), account_key="BGR-001")

    assert (eval_day1["tradovate_symbol"], eval_day1["tradovate_qty"]) == ("MNQZ6", 20)
    assert eval_day1["tradovate_tp_ticks"] == 152
    assert eval_day2["tradovate_tp_ticks"] == 150
    assert eval_day1["tradovate_sl_ticks"] == eval_day2["tradovate_sl_ticks"] == 200
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"] == 425
    assert ft1["tradovate_sl_ticks"] == ft1_repeat["tradovate_sl_ticks"] == 200


def test_blue_guardian_farm_uses_account_base_daily_jitter_and_floor_block(monkeypatch):
    manager = PropFirmManager()
    draws = iter((200.0, 12.0, 160.0, -15.0, 53500.0))
    monkeypatch.setattr(manager, "_draw_uniform", lambda _low, _high: next(draws))

    first_farm = manager.randomize_trade_config(
        "Blue Guardian Reserve", "farming", _config(),
        account_key="BGR-001", balance=54000.0)
    repeat_farm = manager.randomize_trade_config(
        "Blue Guardian Reserve", "farming", _config(),
        account_key="BGR-001", balance=54000.0)
    no_room = manager.randomize_trade_config(
        "Blue Guardian Reserve", "funded_trade2", _config(),
        account_key="BGR-002", balance=50100.0)

    assert first_farm["tradovate_tp_ticks"] == repeat_farm["tradovate_tp_ticks"] == 31
    assert first_farm["tradovate_qty"] == repeat_farm["tradovate_qty"] == 1
    assert first_farm["tradovate_sl_ticks"] == repeat_farm["tradovate_sl_ticks"] == 212
    assert no_room["tradovate_sl_ticks"] == 0
    assert "no room" in no_room["_skip_order_reason"]


def test_simulation_json_contains_account_summaries_and_fd2_after_fd1_payout(tmp_path):
    output_path = tmp_path / "blue_guardian.json"

    run_simulation(
        account_count=4,
        seed=20260915,
        json_path=str(output_path),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["firm"] == "Blue Guardian Reserve"
    assert len(payload["accounts"]) == 4
    assert {account["account"] for account in payload["accounts"]} == {
        "BGR-SIM-001",
        "BGR-SIM-002",
        "BGR-SIM-003",
        "BGR-SIM-004",
    }

    first_account_events = [
        event for event in payload["events"]
        if event.get("account") == "BGR-SIM-001"
    ]
    event_names = [event["event"] for event in first_account_events]
    assert event_names.index("PAYOUT FD1") < event_names.index("FD2")
