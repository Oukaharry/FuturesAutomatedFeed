import json

from tests.simulate_fundednext_rapid_daily_50k import run_simulation


def test_fundednext_rapid_daily_json_uses_updated_blueprint(tmp_path):
    path = tmp_path / "fundednext_rapid_daily.json"
    payload = run_simulation(account_count=20, seed=20260915, json_path=str(path))
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded == payload
    assert loaded["firm"] == "FundedNext Rapid Daily 50K"
    assert len(loaded["accounts"]) == 20

    funded = [event for event in loaded["events"] if event["event"] == "FD1"]
    evaluation_passed_accounts = {
        event["account"] for event in loaded["events"]
        if event["event"] in {"EVAL 1", "EVAL RECOVERY"}
    }
    recovery_losses = {
        event["account"] for event in loaded["events"]
        if event["event"] == "EVAL RECOVERY" and event["outcome"] == "LOSS"
    }
    assert len(funded) == len(evaluation_passed_accounts - recovery_losses)
    assert all(event["qty"] == 2 for event in funded)
    assert all(event["sl_ticks"] == 100 for event in funded)
    assert all(400 <= event["tp_ticks"] <= 500 for event in funded)
    assert all(event["balance"] == 50000.0 for event in funded)

    for account in loaded["accounts"]:
        account_events = [event for event in loaded["events"]
                          if event["account"] == account["account"]]
        eval_events = [event for event in account_events
                       if event["event"].startswith("EVAL")]
        if any(event["event"] == "EVAL RECOVERY" for event in eval_events):
            first_eval = next(event for event in eval_events if event["event"] == "EVAL 1")
            assert first_eval["outcome"] == "LOSS"
        else:
            assert sum(event["event"] == "EVAL 1" for event in eval_events) == 1
            assert all(event["event"] != "EVAL 2" for event in eval_events)

    payouts = [event for event in loaded["events"] if event["event"] == "PAYOUT 1"]
    assert all(0 < event["payout_request_gross"] <= 1200.0 for event in payouts)
    assert all(0 < event["payout_before_provider_fees"] <= 1080.0 for event in payouts)
    assert all(event["retained_balance"] in (50100.0, 52800.0) for event in payouts)


def test_fundednext_rapid_daily_simulates_later_payouts_and_recovery_paths(tmp_path):
    path = tmp_path / "fundednext_rapid_daily.json"
    payload = run_simulation(account_count=20, seed=20260915,
                             json_path=str(path))
    events = payload["events"]

    assert any(event["event"] == "PAYOUT 2" for event in events)
    assert any(event["event"] == "PAYOUT 3" for event in events)
    assert any("RECOVERY" in event["event"] and event["trade"] == "funded_trade4_recovery"
               for event in events)
    assert all(event["qty"] == 2 for event in events
               if event.get("trade", "").startswith("funded_trade"))


def test_first_account_matches_requested_recovery_breach_scenario(tmp_path):
    path = tmp_path / "fundednext_rapid_daily.json"
    payload = run_simulation(account_count=20, seed=20260915,
                             json_path=str(path))
    sequence = [event["event"] for event in payload["events"]
                if event["account"] == "FN-RAPID-001"]

    expected = [
        "EVAL 1",
        "EVAL RECOVERY",
        "FUNDING RESET",
        "FD1",
        "FD1 RECOVERY 1",
        "PAYOUT 1",
        "FD2",
        "PAYOUT 2",
        "FD3",
        "FD3 RECOVERY 1",
        "PAYOUT 3",
        "FD4",
        "FD4 RECOVERY 1",
        "BREACH FD4",
    ]
    assert sequence == expected
