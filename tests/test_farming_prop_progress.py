from dashboard.app import (
    _write_farming_prop_days_and_progress,
    update_evaluations_from_aggregated_data,
)


def test_farming_prop_progress_advances_only_for_profitable_days():
    evaluation = {}
    log = []

    written, complete = _write_farming_prop_days_and_progress(evaluation, [
        {"date": "2026-09-14", "net_pnl": 145.0},
        {"date": "2026-09-15", "net_pnl": -400.0},
        {"date": "2026-09-16", "net_pnl": 210.0},
    ], 2, log)

    assert written == 1
    assert not complete
    assert evaluation["Prop Day 1"] == "210.00"
    assert evaluation["_Prop Day 1 Date"] == "2026-09-16"
    assert evaluation["Date 8"] == "2026-09-16"
    assert evaluation["Prop Progress 1"] == "2/5 9/16/26"
    assert evaluation["Hedge Day 2"] == "THURSDAY"


def test_fifth_profitable_farming_day_queues_funded_trade_two():
    evaluation = {
        "Prop Day 1": "100.00",
        "_Prop Day 1 Date": "2026-09-10",
        "Prop Day 2": "100.00",
        "_Prop Day 2 Date": "2026-09-11",
        "Prop Day 3": "100.00",
        "_Prop Day 3 Date": "2026-09-14",
        "Hedge Day 6": "THURSDAY",
    }
    log = []

    written, complete = _write_farming_prop_days_and_progress(evaluation, [
        {"date": "2026-09-15", "net_pnl": 100.0},
    ], 2, log)

    assert written == 1
    assert complete
    assert evaluation["Prop Progress 4"] == "5/5 9/15/26"
    assert evaluation["Hedge Day 6"] == ""
    assert evaluation["Hedge Result 2.1"] == "WEDNESDAY"


def test_tradovate_only_payload_reconciles_farming_without_hedge_deals():
    evaluations = [{"Account #.1": "FTDFYSLX50914913722"}, {"Account #.1": "FTDFYSLX50969754357"}]

    updated, log, sessions = update_evaluations_from_aggregated_data(
        evaluations,
        raw_deals=[],
        tradovate_farming_days=[{
            "account_name": "FTDFYSLX50914913722",
            "mnq_daily_pnl": [
                {"date": "2026-09-16", "net_pnl": 999.0},
            ],
        }, {
            "account_name": "FTDFYSLX50969754357",
            "mnq_daily_pnl": [
                {"date": "2026-09-15", "net_pnl": 5388.48},
                {"date": "2026-09-16", "net_pnl": 152.40},
            ],
        }],
    )

    assert sessions is None
    assert updated[0]["Prop Day 1"] == "999.00"
    assert updated[1]["Prop Day 1"] == "152.40"
    assert updated[1]["_Prop Day 1 Date"] == "2026-09-16"
    assert updated[1]["Date 8"] == "2026-09-16"
    assert updated[1]["Prop Progress 1"] == "2/5 9/16/26"
    assert updated[1]["Hedge Day 2"] == "THURSDAY"
    assert "Prop Day 2" not in updated[1]
    assert any("Tradovate farming reconciliation" in entry for entry in log)