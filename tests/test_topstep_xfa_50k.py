import json

from trader_companion.prop_firm_manager import PropFirmManager
from tests.simulate_topstep_xfa_50k import run_simulation


def _config():
    return {
        "topstepx_symbol": "NQZ26",
        "topstepx_qty": 2,
        "topstepx_tp_ticks": 400,
        "topstepx_sl_ticks": 200,
    }


def test_topstep_xfa_fixed_eval_and_persistent_ft1():
    manager = PropFirmManager()
    evaluation = manager.randomize_trade_config(
        "TopStep 50K XFA", "challenge_trade1", _config(),
        account_key="xfa-test", balance=0.0)
    ft1 = manager.randomize_trade_config(
        "TopStep 50K XFA", "funded_trade1", _config(),
        account_key="xfa-test", balance=0.0)
    repeat = manager.randomize_trade_config(
        "TopStep 50K XFA", "funded_trade1_recovery", _config(),
        account_key="xfa-test", balance=0.0)

    assert evaluation["topstepx_qty"] == 2
    assert evaluation["topstepx_tp_ticks"] == 152
    assert evaluation["topstepx_sl_ticks"] == 200
    assert 402 <= ft1["topstepx_tp_ticks"] <= 502
    assert ft1["topstepx_tp_ticks"] == repeat["topstepx_tp_ticks"]
    assert ft1["topstepx_sl_ticks"] == 200


def test_topstep_xfa_ft2_and_farming_rules():
    manager = PropFirmManager()
    ft2 = manager.randomize_trade_config(
        "TopStep XFA", "funded_trade2", _config(),
        account_key="xfa-ft2", balance=2000.0)
    farm = manager.randomize_trade_config(
        "TopStep XFA", "farming", _config(),
        account_key="xfa-farm", balance=4000.0)

    assert 200 <= ft2["topstepx_tp_ticks"] <= 600
    assert ft2["topstepx_sl_ticks"] == 200
    assert farm["topstepx_qty"] == 2
    assert farm["topstepx_tp_ticks"] == 154
    assert 450 <= farm["topstepx_sl_ticks"] <= 600


def test_topstep_xfa_json_has_no_cross_account_funded_tp_reuse(tmp_path):
    output_path = tmp_path / "topstep_xfa_50k.json"
    payload = run_simulation(account_count=20, seed=20260915,
                             json_path=str(output_path))
    loaded = json.loads(output_path.read_text(encoding="utf-8"))

    assert loaded == payload
    assert loaded["firm"] == "TopStep 50K XFA"
    assert len(loaded["accounts"]) == 20

    owners = {}
    for event in loaded["events"]:
        if not event["event"].startswith("FD"):
            continue
        tp = event["tp_ticks"]
        owner = owners.setdefault(tp, event["account"])
        assert owner == event["account"]
        assert 0 <= event["tp_ticks"] <= 600
        assert event["sl_ticks"] <= 600

    first = [event for event in loaded["events"]
             if event["account"] == "TOPSTEP-XFA-001"]
    reset = next(event for event in first if event["event"] == "FUNDING RESET")
    fd1 = next(event for event in first if event["event"] == "FD1")
    assert reset["next_balance"] == 0.0
    assert fd1["balance"] == 0.0
