import json

from trader_companion.prop_firm_manager import PropFirmManager
from tests.simulate_mffu_rapid_eod_50k import _calculate_payout, run_simulation


def _config():
    return {
        "tradovate_symbol": "NQZ6",
        "tradovate_qty": 3,
        "tradovate_tp_ticks": 320,
        "tradovate_sl_ticks": 133,
    }


def test_mffu_rapid_eod_fixed_eval_and_persistent_ft1():
    manager = PropFirmManager()
    eval_result = manager.randomize_trade_config(
        "MFFU Rapid EOD", "challenge_trade1", _config(),
        account_key="mffu-test", balance=50000.0)
    ft1 = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade1", _config(),
        account_key="mffu-test", balance=50000.0)
    ft1_repeat = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade1_recovery", _config(),
        account_key="mffu-test", balance=50000.0)

    assert eval_result["tradovate_qty"] == 3
    assert eval_result["tradovate_tp_ticks"] == 51
    assert eval_result["tradovate_sl_ticks"] == 133
    assert 305 <= ft1["tradovate_tp_ticks"] <= 335
    assert ft1["tradovate_tp_ticks"] not in (300, 400)
    assert ft1["tradovate_tp_ticks"] == ft1_repeat["tradovate_tp_ticks"]
    assert ft1["tradovate_sl_ticks"] == 133


def test_mffu_rapid_eod_ft2_plus_is_fresh_and_bounded():
    manager = PropFirmManager()
    draws = []
    for trade_number in range(2, 8):
        result = manager.randomize_trade_config(
            "MFFU Rapid EOD", f"funded_trade{trade_number}", _config(),
            account_key="mffu-fresh", balance=52100.0)
        draws.append(result["tradovate_tp_ticks"])
        assert 267 <= result["tradovate_tp_ticks"] <= 450
        assert result["tradovate_tp_ticks"] not in (300, 400)
        assert result["tradovate_sl_ticks"] == 133
    assert len(set(draws)) > 1


def test_mffu_rapid_eod_farming_keeps_blueprint_tp_and_randomizes_sl():
    manager = PropFirmManager()
    config = {
        "tradovate_symbol": "MNQZ6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 154,
        "tradovate_sl_ticks": 133,
    }
    result = manager.randomize_trade_config(
        "MFFU Rapid EOD", "farming", config,
        account_key="mffu-farming", balance=52100.0)

    assert result["tradovate_tp_ticks"] == 154
    assert 120 <= result["tradovate_sl_ticks"] <= 146


def test_mffu_rapid_eod_restarts_ft1_range_when_exhausted():
    manager = PropFirmManager()
    for ticks in range(305, 336):
        manager._mffu_rapid_eod_tp_owners[ticks] = "prior-cycle"

    result = manager.randomize_trade_config(
        "MFFU Rapid EOD", "funded_trade1", _config(),
        account_key="new-cycle", balance=50000.0)

    selected = result["tradovate_tp_ticks"]
    assert 305 <= selected <= 335
    assert all(owner == "new-cycle"
               for owner in manager._mffu_rapid_eod_tp_owners.values())


def test_mffu_rapid_eod_payout_withdraws_half_and_retains_the_other_half():
    payout, retained = _calculate_payout(
        balance=50000.0 + 305 * 15.0,
        cycle_start=50000.0,
        funded_number=1,
    )

    assert payout == 2287
    assert retained == 52288.0
    assert retained > 52100.0


def test_mffu_rapid_eod_json_has_no_cross_account_funded_tp_reuse(tmp_path):
    output_path = tmp_path / "mffu_rapid_eod_50k.json"
    payload = run_simulation(account_count=20, seed=20260915,
                             json_path=str(output_path))
    loaded = json.loads(output_path.read_text(encoding="utf-8"))

    assert loaded == payload
    assert loaded["firm"] == "MFFU Rapid EOD 50K"
    assert len(loaded["accounts"]) == 20

    owners = {}
    for event in loaded["events"]:
        if not event["event"].startswith("FD"):
            continue
        tp = event["tp_ticks"]
        owner = owners.setdefault(tp, event["account"])
        assert owner == event["account"]
        assert event["sl_ticks"] == 133
        assert event["tp_ticks"] <= 599

    first = [event for event in loaded["events"]
             if event["account"] == "MFFU-EOD-001"]
    assert any(event["event"] == "FUNDING RESET" for event in first)
    assert next(event for event in first if event["event"] == "FD1")["balance"] == 50000.0
