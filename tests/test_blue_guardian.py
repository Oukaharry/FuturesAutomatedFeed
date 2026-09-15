import json

from trader_companion.prop_firm_manager import PropFirmManager
from tests.simulate_blue_guardian import run_simulation


def _config():
    return {
        "tradovate_symbol": "NQU6",
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
