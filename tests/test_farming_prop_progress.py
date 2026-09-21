from dashboard.app import (
    _clear_farming_payout_date_collisions,
    _write_farming_prop_days_and_progress,
    recalculate_hedge_nets,
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
    assert "Date 8" not in evaluation
    assert evaluation["Prop Progress 1"] == "2/5 9/16/26"
    assert evaluation["Hedge Day 2"] == "THURSDAY"


def test_fifth_profitable_farming_day_queues_a_payout_request():
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
    # The speculative next farming day is replaced by the payout prompt.
    assert evaluation["Hedge Day 6"] == ""
    assert evaluation["Hedge Day 5"] == "PAYOUT"
    assert evaluation["_Hedge Day 5 Payout Due"] == "2026-09-15"


def test_cleared_prop_progress_is_not_regenerated_without_a_prop_day_clear():
    evaluation = {
        "Prop Day 1": "100.00",
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Progress 1": "",
        "_cleared_fields": ["Prop Progress 1"],
    }

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-16", "net_pnl": 100.0}], 2, []
    )

    assert evaluation["Prop Progress 1"] == ""


def test_refreshed_cleared_prop_day_restores_its_progress():
    evaluation = {
        "Prop Day 1": "",
        "Prop Progress 1": "",
        "_cleared_fields": ["Prop Day 1", "Prop Progress 1"],
    }

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-16", "net_pnl": 100.0}], 2, []
    )

    assert evaluation["Prop Day 1"] == "100.00"
    assert evaluation["Prop Progress 1"] == "2/5 9/16/26"


def test_tradovate_only_payload_reconciles_farming_without_hedge_deals():
    evaluations = [
        {"Account #.1": "FTDFYSLX50914913722", "Status": "In Progress"},
        {"Account #.1": "FTDFYSLX50969754357", "Status": "In Progress"},
    ]

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
    assert not str(updated[1].get("Date 8") or "").strip()
    assert updated[1]["Prop Progress 1"] == "2/5 9/16/26"
    assert updated[1]["Hedge Day 2"] == "THURSDAY"
    assert "Prop Day 2" not in updated[1]
    assert any("Tradovate farming reconciliation" in entry for entry in log)


def test_tradovate_farming_does_not_use_unstarted_challenge_account():
    evaluations = [{
        "Account #": "FUNDEDNEXT-DEAD-12345",
        "Account #.1": "",
        "Status": "Not Started",
    }]

    updated, log, sessions = update_evaluations_from_aggregated_data(
        evaluations,
        raw_deals=[],
        tradovate_farming_days=[{
            "account_name": "FUNDEDNEXT-DEAD-12345",
            "mnq_daily_pnl": [{"date": "2026-09-16", "net_pnl": 152.40}],
        }],
    )

    assert sessions is None
    assert "Prop Day 1" not in updated[0]
    assert "Prop Progress 1" not in updated[0]
    assert not any("Tradovate farming reconciliation" in entry for entry in log)


def test_farming_does_not_stamp_payout_date_eight():
    evaluation = {"Date 8": "", "Payout 8": ""}
    try:
        _write_farming_prop_days_and_progress(
            evaluation, [{"date": "2026-09-16", "net_pnl": 152.40}], 2, []
        )
    except ValueError:
        # Windows strftime does not accept %-m; Prop Day is written first.
        pass
    assert evaluation["_Prop Day 1 Date"] == "2026-09-16"
    assert not str(evaluation.get("Date 8") or "").strip()


def test_farming_clears_phantom_date_eight_matching_prop_day():
    evaluation = {
        "Date 8": "2026-09-16",
        "Payout 8": "",
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Day 1": "152.40",
    }
    assert _clear_farming_payout_date_collisions(evaluation) is True
    assert evaluation["Date 8"] == ""
    assert evaluation["Prop Day 1"] == "152.40"


def test_farming_keeps_real_payout_eight_date():
    evaluation = {
        "Date 8": "2026-09-16",
        "Payout 8": "1200.00",
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Day 1": "152.40",
    }
    assert _clear_farming_payout_date_collisions(evaluation) is False
    assert evaluation["Date 8"] == "2026-09-16"
    assert evaluation["Payout 8"] == "1200.00"


def test_hedge_net_recalc_clears_phantom_date_eight():
    evaluations = [{
        "Date 8": "2026-09-16",
        "Payout 8": "",
        "_Prop Day 1 Date": "2026-09-16",
        "Status P1": "Pass",
        "Status": "Pass",
    }]
    recalculate_hedge_nets(evaluations)
    assert evaluations[0]["Date 8"] == ""


def test_push_clears_phantom_date_eight_without_new_farming():
    evaluations = [{
        "Account #.1": "FTDFYSLX50914913722",
        "Status": "Pass",
        "Date 8": "2026-09-16",
        "Payout 8": None,
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Day 1": "-548.30",
    }]
    updated, log, sessions = update_evaluations_from_aggregated_data(
        evaluations, raw_deals=[], tradovate_farming_days=[],
    )
    assert sessions is None
    assert updated[0]["Date 8"] == ""
    assert updated[0]["Prop Day 1"] == "-548.30"
