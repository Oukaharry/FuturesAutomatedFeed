from dashboard.app import (
    _clear_farming_payout_date_collisions,
    _resume_after_manual_payout_clear,
    _write_farming_prop_days_and_progress as _write_farming_impl,
    recalculate_hedge_nets,
    update_evaluations_from_aggregated_data,
)


def _write_farming_prop_days_and_progress(evaluation, days, row_num, log, today=None):
    """Default `today` to the payload's newest day so tests stay date-agnostic."""
    return _write_farming_impl(
        evaluation, days, row_num, log, today=today or days[-1]["date"]
    )


def _traded(evaluation, days):
    """Mark Hedge Day 1..days filled, which is what the companion does on a fill."""
    for slot in range(1, days + 1):
        evaluation.setdefault(f"Hedge Day {slot}", "$0.00")
    return evaluation


def test_farming_prop_progress_advances_only_for_profitable_days():
    evaluation = _traded({}, 1)
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
    _traded(evaluation, 4)
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


def test_day_below_the_firm_minimum_does_not_advance_the_counter():
    evaluation = {
        "Prop Firm": "Blue Guardian Reserve",
        "Prop Day 1": "152.00",
        "_Prop Day 1 Date": "2026-09-14",
    }
    _traded(evaluation, 2)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 120.0}], 2, []
    )

    assert evaluation["Prop Day 2"] == "120.00"
    # Prop Day 1 cleared $150, Prop Day 2 did not, so the count holds at 2/5.
    assert evaluation["Prop Progress 1"] == "2/5 9/14/26"
    assert evaluation["Prop Progress 2"] == "2/5 9/15/26"


def test_firm_requiring_six_qualifying_days_is_not_complete_at_five():
    evaluation = {
        "Prop Firm": "Funding Ticks PRO+",
        "Prop Day 1": "210.00",
        "_Prop Day 1 Date": "2026-09-10",
        "Prop Day 2": "210.00",
        "_Prop Day 2 Date": "2026-09-11",
        "Prop Day 3": "210.00",
        "_Prop Day 3 Date": "2026-09-14",
    }
    _traded(evaluation, 4)

    written, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 210.0}], 2, []
    )

    assert written == 1
    assert not complete
    assert evaluation["Prop Progress 4"] == "5/6 9/15/26"
    assert evaluation["Hedge Day 5"] == "WEDNESDAY"


def test_second_payout_cycle_restarts_the_counter_in_the_next_slots():
    evaluation = {
        "Prop Day 1": "100.00",
        "_Prop Day 1 Date": "2026-09-10",
        "Prop Day 2": "100.00",
        "_Prop Day 2 Date": "2026-09-11",
        "Prop Day 3": "100.00",
        "_Prop Day 3 Date": "2026-09-14",
        "Prop Day 4": "100.00",
        "_Prop Day 4 Date": "2026-09-15",
        "_Farming Cycle Start": 5,
    }
    _traded(evaluation, 5)

    written, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-16", "net_pnl": 100.0}], 2, []
    )

    assert written == 1
    assert not complete
    assert evaluation["Prop Day 5"] == "100.00"
    # Cycle 1's four days are behind us; this is the new cycle's first farm day.
    assert evaluation["Prop Progress 5"] == "2/5 9/16/26"
    assert "Prop Progress 1" not in evaluation


def test_completing_a_cycle_records_where_the_next_cycle_starts():
    evaluation = {
        "Prop Day 1": "100.00",
        "_Prop Day 1 Date": "2026-09-10",
        "Prop Day 2": "100.00",
        "_Prop Day 2 Date": "2026-09-11",
        "Prop Day 3": "100.00",
        "_Prop Day 3 Date": "2026-09-14",
    }
    _traded(evaluation, 4)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 100.0}], 2, []
    )

    assert evaluation["_Farming Cycle Start"] == 5


def test_a_firm_without_farming_days_is_payable_after_the_funded_trade():
    evaluation = _traded({"Prop Firm": "FundedNext Rapid Daily"}, 1)

    written, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 100.0}], 2, []
    )

    assert written == 1
    assert complete
    assert evaluation["Prop Progress 1"] == "1/1 9/15/26"
    assert evaluation["Hedge Day 2"] == "PAYOUT"


def test_rapid_daily_does_not_inherit_the_fundednext_farming_rule():
    evaluation = _traded({"Prop Firm": "FundedNext Rapid Daily 50K"}, 1)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 100.0}], 2, []
    )

    assert evaluation["Prop Progress 1"].startswith("1/1")


def test_mffu_flex_uses_the_farming_tp_minimum():
    evaluation = _traded({"Prop Firm": "My Funded Futures"}, 1)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 120.0}], 2, []
    )

    # $120 is short of the $150 the farming TP covers, so the day does not count.
    assert evaluation["Prop Progress 1"] == "1/5 9/15/26"


def test_mffu_builder_is_not_swallowed_by_the_mffu_farming_rule():
    evaluation = _traded({"Prop Firm": "MFFU Builder 50K"}, 1)

    _, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-15", "net_pnl": 120.0}], 2, []
    )

    assert complete
    assert evaluation["Prop Progress 1"].startswith("1/1")


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
    _traded(evaluation, 1)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-16", "net_pnl": 100.0}], 2, []
    )

    assert evaluation["Prop Day 1"] == "100.00"
    assert evaluation["Prop Progress 1"] == "2/5 9/16/26"


def test_tradovate_only_payload_reconciles_farming_without_hedge_deals():
    evaluations = [
        _traded({"Account #.1": "FTDFYSLX50914913722", "Status": "In Progress"}, 1),
        _traded({"Account #.1": "FTDFYSLX50969754357", "Status": "In Progress"}, 1),
    ]

    updated, log, sessions = update_evaluations_from_aggregated_data(
        evaluations,
        raw_deals=[],
        today="2026-09-16",
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
    evaluation = _traded({"Date 8": "", "Payout 8": ""}, 1)
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


def test_prop_day_follows_the_traded_hedge_day_not_the_first_free_cell():
    # Prop Day 1 was hand-entered and Prop Day 2 left blank, but only four
    # Hedge Days have traded, so today's P/L belongs to Prop Day 4.
    evaluation = {
        "Prop Day 1": "-548.30",
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Day 3": "150.20",
        "_Prop Day 3 Date": "2026-09-18",
    }
    _traded(evaluation, 4)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-22", "net_pnl": 150.20}], 2, []
    )

    assert evaluation["Prop Day 4"] == "150.20"
    assert evaluation["_Prop Day 4 Date"] == "2026-09-22"
    assert "Prop Day 2" not in evaluation


def test_no_prop_day_is_written_before_a_farming_trade_fills():
    evaluation = {"Hedge Day 1": "MONDAY"}

    written, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-22", "net_pnl": 150.20}], 2, []
    )

    assert written == 0
    assert not complete
    assert "Prop Day 1" not in evaluation


def test_older_history_does_not_overwrite_the_day_already_recorded():
    evaluation = {
        "Prop Day 1": "150.20",
        "_Prop Day 1 Date": "2026-09-21",
    }
    _traded(evaluation, 1)

    written, _complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-18", "net_pnl": 999.0}], 2, []
    )

    assert written == 0
    assert evaluation["Prop Day 1"] == "150.20"


def test_repushing_the_same_day_keeps_its_slot():
    evaluation = {
        "Prop Day 4": "150.20",
        "_Prop Day 4 Date": "2026-09-22",
    }
    _traded(evaluation, 4)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-22", "net_pnl": 150.20}], 2, []
    )

    assert evaluation["Prop Day 4"] == "150.20"
    assert "Prop Day 5" not in evaluation


def test_a_pending_payout_blocks_the_next_farming_day():
    # The payout prompt is still outstanding, so nothing new may be recorded
    # against this row — that is what used to open a phantom second cycle.
    evaluation = {
        "Prop Day 1": "150.20",
        "_Prop Day 1 Date": "2026-09-16",
        "Hedge Day 5": "PAYOUT",
    }
    _traded(evaluation, 4)
    log = []

    written, complete = _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-22", "net_pnl": 150.20}], 2, log
    )

    assert written == 0
    assert complete
    assert evaluation["Hedge Day 5"] == "PAYOUT"
    assert "Prop Day 4" not in evaluation
    assert "Prop Progress 4" not in evaluation
    assert any("awaiting a payout" in entry for entry in log)


def test_clearing_payout_by_hand_queues_the_next_funded_trade():
    evaluation = {
        "Hedge Result 1.1": "$0.00",
        "Hedge Result 2.1": "0",
        "Hedge Day 5": "",
        "_Hedge Day 5 Payout Due": "2026-09-21",
        "_cleared_fields": ["Hedge Day 5"],
    }

    queued = _resume_after_manual_payout_clear(evaluation)

    assert queued == "Hedge Result 3.1"
    assert evaluation["Hedge Result 3.1"] in (
        "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
    )
    # The cleared prompt's slot opens the next cycle.
    assert evaluation["_Farming Cycle Start"] == 5
    # The anchor is spent, so a later push cannot queue a second trade.
    assert "_Hedge Day 5 Payout Due" not in evaluation
    assert _resume_after_manual_payout_clear(evaluation) is None


def test_first_farming_day_after_a_payout_counts_as_two_of_five():
    # Four qualifying days and a payout are behind us; the funded trade is day
    # one of the new cycle, so the first farming day that closes reads 2/5.
    evaluation = {
        "Prop Day 1": "152.40",
        "_Prop Day 1 Date": "2026-09-16",
        "Prop Day 2": "150.20",
        "_Prop Day 2 Date": "2026-09-17",
        "Prop Day 3": "150.20",
        "_Prop Day 3 Date": "2026-09-18",
        "Prop Day 4": "150.20",
        "_Prop Day 4 Date": "2026-09-21",
        "Prop Progress 4": "5/5 9/21/26",
        "_Farming Cycle Start": 5,
    }
    _traded(evaluation, 5)

    _write_farming_prop_days_and_progress(
        evaluation, [{"date": "2026-09-23", "net_pnl": 150.20}], 2, []
    )

    assert evaluation["Prop Day 5"] == "150.20"
    assert evaluation["Prop Progress 5"] == "2/5 9/23/26"
    assert evaluation["Prop Progress 4"] == "5/5 9/21/26"


def test_clearing_payout_drops_a_farming_day_queued_against_the_prompt():
    # Two live placeholders on one row would fire two trades.
    evaluation = {
        "Hedge Result 1.1": "$0.00",
        "Hedge Day 5": "WEDNESDAY",
        "_Hedge Day 5 Payout Due": "2026-09-21",
        "_cleared_fields": ["Hedge Day 5"],
    }

    queued = _resume_after_manual_payout_clear(evaluation)

    assert queued == "Hedge Result 2.1"
    assert evaluation["Hedge Day 5"] == ""


def test_a_payout_still_showing_is_not_treated_as_cleared():
    evaluation = {
        "Hedge Result 1.1": "$0.00",
        "Hedge Day 5": "PAYOUT",
        "_Hedge Day 5 Payout Due": "2026-09-21",
        "_cleared_fields": ["Hedge Day 5"],
    }

    assert _resume_after_manual_payout_clear(evaluation) is None
    assert "Hedge Result 2.1" not in evaluation


def test_a_payout_never_stamped_is_not_treated_as_cleared():
    evaluation = {"Hedge Day 5": "", "_cleared_fields": ["Hedge Day 5"]}

    assert _resume_after_manual_payout_clear(evaluation) is None


def test_only_todays_session_is_recorded():
    # The account last traded on the 21st; nothing closed today, so the row
    # must not absorb that older day into a fresh slot.
    evaluation = {}
    _traded(evaluation, 1)
    log = []

    written, complete = _write_farming_impl(
        evaluation,
        [{"date": "2026-09-21", "net_pnl": 150.20}],
        2,
        log,
        today="2026-09-22",
    )

    assert written == 0
    assert not complete
    assert "Prop Day 1" not in evaluation
    assert any("is not today" in entry for entry in log)


def test_history_before_today_is_ignored_and_only_today_is_written():
    evaluation = {}
    _traded(evaluation, 1)

    _write_farming_impl(
        evaluation,
        [
            {"date": "2026-09-16", "net_pnl": -548.30},
            {"date": "2026-09-17", "net_pnl": 150.20},
            {"date": "2026-09-22", "net_pnl": 152.40},
        ],
        2,
        [],
        today="2026-09-22",
    )

    assert evaluation["Prop Day 1"] == "152.40"
    assert evaluation["_Prop Day 1 Date"] == "2026-09-22"
    assert "Prop Day 2" not in evaluation


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


def test_seed_farming_history_backfills_empty_row():
    from dashboard.app import _seed_farming_history

    evaluation = {"Prop Firm": "Tradeify", "Status": "In Progress"}
    log = []

    seeded = _seed_farming_history(evaluation, [
        {"date": "2026-09-16", "net_pnl": 143.10},
        {"date": "2026-09-17", "net_pnl": 154.00},
        {"date": "2026-09-18", "net_pnl": 154.00},
        {"date": "2026-09-21", "net_pnl": 154.00},
    ], 2, log)

    assert seeded == 4
    assert evaluation["Prop Day 1"] == "143.10"
    assert evaluation["_Prop Day 1 Date"] == "2026-09-16"
    assert evaluation["Prop Day 4"] == "154.00"
    assert evaluation["_Prop Day 4 Date"] == "2026-09-21"
    # 143.10 is under Tradeify's $150 qualifying floor, so day 1 stays 1/5;
    # the funded TP is implicit day 1 and each $154 day advances one step.
    assert evaluation["Prop Progress 1"] == "1/5 9/16/26"
    assert evaluation["Prop Progress 4"] == "4/5 9/21/26"
    assert any("seeded 4 Prop Day" in line for line in log)


def test_seed_farming_history_never_touches_rows_with_records():
    from dashboard.app import _seed_farming_history

    with_hedge = {"Hedge Day 1": "$0.00"}
    assert _seed_farming_history(with_hedge, [
        {"date": "2026-09-16", "net_pnl": 100.0},
    ], 2, []) == 0
    assert "Prop Day 1" not in with_hedge

    with_prop = {"Prop Day 2": "50.00"}
    assert _seed_farming_history(with_prop, [
        {"date": "2026-09-16", "net_pnl": 100.0},
    ], 2, []) == 0
    assert "Prop Day 1" not in with_prop
