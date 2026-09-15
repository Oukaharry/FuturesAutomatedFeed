import json

from trader_companion.prop_firm_manager import PropFirmManager
from tests.simulate_lucid_flex_50k import run_simulation


def _config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 140,
        "tradovate_sl_ticks": 200,
    }


def test_lucid_flex_eval_size_and_fixed_values_are_persistent():
    manager = PropFirmManager()
    first = manager.randomize_trade_config(
        "Lucid", "challenge_trade1", _config(), account_key="lucid-eval")
    second = manager.randomize_trade_config(
        "Lucid", "challenge_trade2", _config(), account_key="lucid-eval")

    assert first["tradovate_qty"] in (1, 2)
    assert second["tradovate_qty"] == first["tradovate_qty"]
    assert first["tradovate_tp_ticks"] == (304 if first["tradovate_qty"] == 1 else 152)
    assert first["tradovate_sl_ticks"] == (400 if first["tradovate_qty"] == 1 else 200)
    assert second["tradovate_tp_ticks"] == first["tradovate_tp_ticks"]
    assert second["tradovate_sl_ticks"] == first["tradovate_sl_ticks"]


def test_lucid_flex_ft1_is_persistent_and_ft2_uses_cycle_start(monkeypatch):
    manager = PropFirmManager()
    monkeypatch.setattr(manager, "_draw_uniform", lambda low, high: 1600.0)

    ft1 = manager.randomize_trade_config(
        "Lucid", "funded_trade1", _config(), account_key="lucid-formula",
        balance=50000.0)
    ft1_repeat = manager.randomize_trade_config(
        "Lucid", "funded_trade1_recovery", _config(),
        account_key="lucid-formula", balance=50000.0)
    assert 53000 <= ft1["_randomization"]["target_dollars"] <= 54000
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_sl_ticks"] == 200

    ft2 = manager.randomize_trade_config(
        "Lucid", "funded_trade2", {**_config(), "cycle_start": 51500.0},
        account_key="lucid-formula", balance=52800.0)
    assert ft2["_randomization"]["offset_dollars"] == 1600.0
    assert ft2["tradovate_tp_ticks"] == 31
    assert ft2["tradovate_sl_ticks"] == 270


def test_lucid_flex_20_account_json_has_unique_funded_tp_by_account(tmp_path):
    output_path = tmp_path / "lucid_flex_50k.json"
    payload = run_simulation(account_count=20, seed=20260915,
                             json_path=str(output_path))
    loaded = json.loads(output_path.read_text(encoding="utf-8"))

    assert loaded == payload
    assert loaded["firm"] == "Lucid Flex 50K"
    assert len(loaded["accounts"]) == 20

    funded_events = [event for event in loaded["events"]
                     if event["event"].startswith("FD")]
    owners_by_tp = {}
    for event in funded_events:
        previous_owner = owners_by_tp.setdefault(event["tp_ticks"], event["account"])
        assert previous_owner == event["account"]

    first_account_events = [event for event in loaded["events"]
                            if event["account"] == "LUCID-SIM-001"]
    assert any(event["event"] == "EVAL 1" for event in first_account_events)
    reset = next(event for event in first_account_events
                 if event["event"] == "FUNDING RESET")
    fd1_events = [event for event in first_account_events
                  if event["event"] == "FD1"]
    assert reset["next_balance"] == 50000.0
    assert fd1_events
    assert all(event["balance"] == 50000.0 for event in fd1_events)
