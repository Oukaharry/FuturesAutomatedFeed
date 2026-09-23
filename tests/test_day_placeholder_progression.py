from datetime import datetime

import pytest

from trader_companion.trader_app import TradeOpssAIApp
from trader_companion.prop_firm_manager import PropFirmManager


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    return app


def test_challenge_final_slot_queues_funded_without_funded_account_number():
    app = _app()
    evaluation = {"Account #": "challenge-only"}

    assert app._resolve_next_hedge_field(
        evaluation, "MFFU Rapid EOD", "Challenge", "Hedge Result 4"
    ) == "Hedge Result 1.1"

def _scrub_app():
    app = _app()
    app.log = lambda *args, **kwargs: None
    return app


def _row(**overrides):
    row = {
        "Account #": "FNFT-1",
        "Hedge Result 1": "MON",
        "Hedge Result 2": "150.00",
        "Hedge Day 1": "TUE",
        "Prop Day 1": "WED",
    }
    row.update(overrides)
    return row


def test_failed_row_day_placeholders_are_cleared_and_forced():
    app = _scrub_app()
    row = _row(**{"Status P1": "Fail"})

    cleared = app._scrub_failed_row_day_placeholders([row])

    assert set(cleared) == {"Hedge Result 1", "Hedge Day 1", "Prop Day 1"}
    assert row["Hedge Result 1"] == ""
    assert row["Hedge Day 1"] == ""
    assert row["Prop Day 1"] == ""
    # Realised P&L must survive the scrub.
    assert row["Hedge Result 2"] == "150.00"


def test_breached_funded_row_is_scrubbed():
    app = _scrub_app()
    row = _row(**{"Account #.1": "FNFT-2", "Status P1": "Pass", "Status": "Breached"})

    assert app._scrub_failed_row_day_placeholders([row])
    assert row["Hedge Result 1"] == ""


def test_failed_challenge_with_live_funded_leg_keeps_placeholders():
    """The funded account still trades, so its queued days must survive."""
    app = _scrub_app()
    row = _row(**{"Account #.1": "FNFT-2", "Status P1": "Fail", "Status": "In Progress"})

    assert app._scrub_failed_row_day_placeholders([row]) == []
    assert row["Hedge Result 1"] == "MON"


def test_active_row_is_untouched():
    app = _scrub_app()
    row = _row(**{"Status P1": "In Progress"})

    assert app._scrub_failed_row_day_placeholders([row]) == []
    assert row["Hedge Result 1"] == "MON"


def test_successful_challenge_fill_marks_status_p1_in_progress():
    row = _row(**{"Status P1": "Not Started"})

    assert _app()._mark_trade_in_progress(row) == "Status P1"
    assert row["Status P1"] == "In Progress"


def test_successful_funded_fill_marks_funded_status_in_progress():
    row = _row(**{"Account #.1": "FNFT-funded", "Status": "Not Started"})

    assert _app()._mark_trade_in_progress(row) == "Status"
    assert row["Status"] == "In Progress"


def test_funded_account_date_and_payout_mark_sparse_row_as_ft2():
    row = {
        "Account #.1": "FTDFYSL-funded",
        "Date Started.1": "2026-09-15",
        "Payout 1": "$1,000.00",
    }
    app = _app()

    assert app._on_funded_leg(row) is True
    assert app._has_taken_funded_trade1(row) is True
    assert app._has_taken_funded_trade2(row) is True


def test_sparse_funded_breach_writes_funded_status_field():
    row = {
        "Account #.1": "FTDFYSL-funded",
        "Date Started.1": "2026-09-15",
        "Payout 1": "$1,000.00",
        "Status P1": "Pass",
        "Status": "Hit TP1",
    }
    app = _scrub_app()
    app._derive_account_status = lambda evaluation: ("Fail", "balance below funded floor")

    assert app._apply_status_update(row) == ["Status"]
    assert row["Status"] == "Fail"
    assert row["Status P1"] == "Pass"


def test_sparse_funded_payout_row_breaches_at_ft2_floor_from_history():
    row = {
        "Prop Firm": "Tradeify (50% Add-On)",
        "Account #.1": "FTDFYSL-funded",
        "Date Started.1": "2026-09-15",
        "Payout 1": "$1,000.00",
    }
    app = _scrub_app()
    app._trade_outcome_history = lambda: {
        "ftdfysl-funded": {
            "balance": 50078.64,
            "daily_pnl": [{"trades": 1, "net_pnl": -147.28}],
        }
    }
    app._detect_payouts = lambda account: []

    status, reason = app._derive_account_status(row)

    assert status == "Fail"
    assert "50,078.64" in reason
    assert "50,100.00" in reason


def test_successful_fill_does_not_replace_terminal_status():
    row = _row(**{"Status P1": "Pass"})

    assert _app()._mark_trade_in_progress(row) is None
    assert row["Status P1"] == "Pass"


def _status_app(outcome):
    app = _scrub_app()
    app._derive_account_status = lambda row: (None, None)
    app._latest_resolved_outcome = lambda account: ("2026-09-23", outcome)
    return app


def test_resolved_win_marks_challenge_status_hit_tp_for_trade_number():
    row = _row(**{
        "Hedge Result 1": "$0.00",
        "Hedge Result 2": "TUESDAY",
        "Status P1": "In Progress",
    })
    app = _status_app("win")

    assert app._apply_status_update(row) == ["Status P1"]
    assert row["Status P1"] == "Hit TP1"


def test_resolved_loss_marks_challenge_status_hit_sl_for_trade_number():
    row = _row(**{
        "Hedge Result 1": "100.00",
        "Hedge Result 2": "$0.00",
        "Hedge Result 3": "THURSDAY",
        "Status P1": "Hit TP1",
    })
    app = _status_app("loss")

    assert app._apply_status_update(row) == ["Status P1"]
    assert row["Status P1"] == "Hit SL2"


def test_trade_marker_does_not_replace_manual_status():
    row = _row(**{"Status P1": "Paused"})
    app = _status_app("win")

    assert app._apply_status_update(row) == []
    assert row["Status P1"] == "Paused"


def test_confirmed_breach_replaces_provisional_hit_tp_status():
    row = _row(**{"Status P1": "Hit TP1"})
    app = _scrub_app()
    app._derive_account_status = lambda evaluation: ("Fail", "balance below breach floor")

    assert app._apply_status_update(row) == ["Status P1"]
    assert row["Status P1"] == "Fail"


def test_confirmed_funded_breach_replaces_stale_pass_status():
    row = {
        "Account #": "FTDFYSL-funded",
        "Date Started": "2026-09-15",
        "Status": "Pass",
    }
    app = _scrub_app()
    app._derive_account_status = lambda evaluation: ("Fail", "balance below funded floor")

    assert app._apply_status_update(row) == ["Status"]
    assert row["Status"] == "Fail"


def test_open_broker_position_blocks_dashboard_outcome_update():
    class Broker:
        def has_open_position_for_account(self, account):
            assert account == "FNFT-1"
            return True, account

    app = _scrub_app()
    app._broker_connections = {"FundedNext": {"account": Broker()}}

    assert app._account_has_open_position(_row(**{"Prop Firm": "FundedNext"})) is True


def test_flat_broker_position_allows_dashboard_outcome_update():
    class Broker:
        def has_open_position_for_account(self, account):
            assert account == "FNFT-1"
            return False, account

    app = _scrub_app()
    app._broker_connections = {"FundedNext": {"account": Broker()}}

    assert app._account_has_open_position(_row(**{"Prop Firm": "FundedNext"})) is False


def test_all_trade_phases_use_the_general_close_watcher():
    class Root:
        def after(self, delay, callback):
            assert delay == 5000

    app = _scrub_app()
    app.root = Root()
    app._pending_farming_closes = {}
    app._farming_close_poll_active = False
    broker = object()

    app._track_account_close(broker, "FNFT-1")

    assert app._pending_farming_closes["fnft-1"]["broker"] is broker
    assert app._farming_close_poll_active is True


def test_recovery_uses_shared_funded_next_connection_for_flex_rows():
    class Broker:
        def has_open_position_for_account(self, account):
            return False, account

    app = _scrub_app()
    app._broker_connections = {"Funded Next": {"account": Broker()}}
    app._locate_progression_cells = lambda row: ("Hedge Result 1", "Challenge", "Hedge Result 2")
    tracked = []
    app._track_account_close = lambda broker, account: tracked.append((broker, account))
    row = _row(**{"Prop Firm": "FundedNext Flex", "Hedge Result 1": "$0.00"})

    app._resume_pending_account_closes([row])

    assert len(tracked) == 1
    assert tracked[0][1] == "FNFT-1"


def test_completed_trade_with_queued_day_requires_fresh_history():
    app = _scrub_app()
    row = _row(**{"Hedge Result 1": "$0.00", "Hedge Result 2": "THURSDAY"})

    assert app._outcome_history_needed(row) is True


def test_tradeify_select_funded_trade_two_stop_uses_live_floor_buffer():
    config = {"tradovate_qty": 2, "tradovate_sl_ticks": 260}

    adjusted = TradeOpssAIApp._apply_tradeify_select_ft2_stop(
        config, balance=52941.0, tick_value=5.0)

    assert adjusted["tradovate_sl_ticks"] == 284
    assert adjusted["tradovate_sl_ticks"] * adjusted["tradovate_qty"] * 5 == 2840
    assert "_skip_order_reason" not in adjusted


def test_tradeify_select_funded_trade_two_is_blocked_at_floor():
    config = {"tradovate_qty": 2, "tradovate_sl_ticks": 260}

    adjusted = TradeOpssAIApp._apply_tradeify_select_ft2_stop(
        config, balance=50100.0, tick_value=5.0)

    assert "no room above the $50,100 floor" in adjusted["_skip_order_reason"]


@pytest.mark.parametrize("trade_index", [1, 2, 3, 4, 5])
def test_every_funded_trade_sizes_stop_from_live_balance_and_floor(trade_index):
    manager = PropFirmManager()
    config = {"tradovate_qty": 2, "tradovate_sl_ticks": 200}

    adjusted = manager.calculate_funded_sl(
        config, current_balance=52941.0, threshold=50100.0,
        trade_index=trade_index, tick_value=5.0)

    assert adjusted["tradovate_sl_ticks"] == 284
    assert adjusted["tradovate_sl_ticks"] * 2 * 5 == 2840


def test_untraded_day_placeholder_does_not_require_history_refresh():
    app = _scrub_app()
    row = _row(**{"Hedge Result 1": "THURSDAY"})

    assert app._outcome_history_needed(row) is False


def test_trading_window_allows_one_am_through_before_eight_pm_eat():
    app = _scrub_app()

    assert app._trading_window_open(datetime(2026, 9, 23, 1, 0))[0] is True
    assert app._trading_window_open(datetime(2026, 9, 23, 19, 59))[0] is True
    assert app._trading_window_open(datetime(2026, 9, 23, 20, 0))[0] is False
    assert app._trading_window_open(datetime(2026, 9, 23, 0, 59))[0] is False


LIVE_BLUEPRINT = {
    "tradovate_symbol": "NQZ6",
    "tradovate_qty": 2,
    "tradovate_tp_ticks": 540,
    "tradovate_sl_ticks": 200,
    "mt5_volume": 15,
    "mt5_tp_points": 46,
    "mt5_sl_points": 139,
}


def test_live_account_uses_fixed_blueprint_whatever_the_phase():
    app = _scrub_app()
    live = {"Status P1": "Live", "Account #": "LIVE-1"}

    for phase in ("challenge_trade1", "funded_trade1", "funded_trade5",
                  "farming", "cycle_trade_a", "qualifying_day"):
        config = app._live_account_config(live)
        for key, value in LIVE_BLUEPRINT.items():
            assert config[key] == value, (phase, key)

    assert app._live_account_config({"Status P1": "In Progress"}) is None


def test_live_config_survives_the_tp_sl_adjustment_pipeline():
    app = _scrub_app()
    live = {"Status P1": "Live", "Account #": "LIVE-1"}
    config = app._live_account_config(live)

    adjusted = app._apply_tp_sl_adjustments(
        config.copy(), broker_account=None, platform="Tradovate",
        firm_code="Tradeify", current_phase="Funded", phase_key="funded_trade2",
        acct_size="$50,000", row_eval=live, acct_num="LIVE-1", is_farming=False)

    assert adjusted == config
    assert adjusted["tradovate_tp_ticks"] == 540
    assert adjusted["tradovate_sl_ticks"] == 200

def test_funded_entries_queue_farming_for_firms_that_require_it():
    app = _app()
    evaluation = {"Account #.1": "funded"}

    assert app._resolve_next_hedge_field(
        evaluation, "MFFU Rapid EOD", "Funded", "Hedge Result 1.1"
    ) == "Hedge Day 1"
    assert app._resolve_next_hedge_field(
        evaluation, "TopStep 50K XFA", "Funded", "Hedge Result 2.1"
    ) == "Hedge Day 1"
    assert app._resolve_next_hedge_field(
        evaluation, "FTMO Futures Pro", "Funded", "Hedge Result 1.1"
    ) == "Hedge Day 1"


def test_farming_entries_continue_through_farming_day_cells():
    app = _app()
    evaluation = {"Account #.1": "funded", "Hedge Day 1": "$0.00"}

    assert app._resolve_next_hedge_field(
        evaluation, "Tradeify Select", "Farming", "Hedge Day 1"
    ) == "Hedge Day 2"


def test_farming_day_three_never_backfills_an_earlier_empty_day():
    app = _app()
    evaluation = {
        "Account #.1": "funded",
        "Hedge Day 2": "$0.00",
        "Hedge Day 3": "$0.00",
    }

    assert app._resolve_next_hedge_field(
        evaluation, "Tradeify Select", "Farming", "Hedge Day 3"
    ) == "Hedge Day 4"


def test_rapid_daily_without_farming_continues_to_next_funded_slot():
    app = _app()
    evaluation = {"Account #.1": "funded"}

    assert app._resolve_next_hedge_field(
        evaluation, "FundedNext Rapid Daily", "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 2.1"


def _payout_app(payouts):
    app = _scrub_app()
    app._detect_payouts = lambda account: list(payouts)
    return app


def _payout_row(**overrides):
    row = {
        "Account #": "FNFT-1",
        "Account #.1": "FNFT-2",
        "Status P1": "Pass",
        "Hedge Result 1.1": "1200.00",
        "Prop Day 4": "150.20",
        "Hedge Day 5": "PAYOUT",
        "_Hedge Day 5 Payout Due": "2026-09-21",
    }
    row.update(overrides)
    return row


def test_payout_marker_blocks_trading():
    app = _scrub_app()

    assert app._eval_has_payout(_payout_row()) is True
    assert app._eval_has_payout(_payout_row(**{"Hedge Day 5": ""})) is False
    # A funded cell typed by hand blocks the same way.
    assert app._eval_has_payout({"Hedge Result 2.1": "PAYOUT"}) is True


def test_payout_marker_is_held_until_the_withdrawal_lands():
    app = _payout_app([])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Day 5"] == "PAYOUT"


def test_older_payouts_do_not_release_the_marker():
    app = _payout_app([("2026-08-14", 1500.0)])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Day 5"] == "PAYOUT"


def test_detected_payout_queues_the_next_funded_trade():
    app = _payout_app([("2026-08-14", 1500.0), ("2026-09-23", 2100.0)])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == [
        "Hedge Day 5", "Hedge Result 2.1"]
    assert row["Hedge Day 5"] == ""
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]
    assert app._eval_has_payout(row) is False
    # The anchor is spent; a later pass must not re-release the same payout.
    assert "_Hedge Day 5 Payout Due" not in row


def test_dashboard_payouts_queue_the_matching_next_funded_trade(monkeypatch):
    app = _scrub_app()
    row = _payout_row(**{
        "Hedge Day 5": "",
        "Payout 1": "$1,500.00",
        "Date 1": "2026-09-23",
    })
    monkeypatch.setattr(
        "trader_companion.trader_app.kenya_now",
        lambda: datetime(2026, 9, 23, 15, 0),
    )

    assert app._release_dashboard_payout_placeholders([row]) == [
        "Hedge Result 2.1", "_Dashboard Payouts Released"]
    assert row["Hedge Result 2.1"] == "WEDNESDAY"
    assert row["_Dashboard Payouts Released"] == 1
    assert app._release_dashboard_payout_placeholders([row]) == []


def test_dashboard_payout_before_eight_pm_keeps_today_placeholder(monkeypatch):
    app = _scrub_app()
    row = _payout_row(**{
        "Hedge Day 5": "",
        "Payout 1": "$1,500.00",
        "Date 1": "2026-09-25",
    })
    monkeypatch.setattr(
        "trader_companion.trader_app.kenya_now",
        lambda: datetime(2026, 9, 25, 17, 0),
    )

    app._release_dashboard_payout_placeholders([row])

    assert row["Hedge Result 2.1"] == "FRIDAY"


def test_dashboard_payout_at_eight_pm_queues_next_trading_day(monkeypatch):
    app = _scrub_app()
    row = _payout_row(**{
        "Hedge Day 5": "",
        "Payout 1": "$1,500.00",
        "Date 1": "2026-09-25",
    })
    monkeypatch.setattr(
        "trader_companion.trader_app.kenya_now",
        lambda: datetime(2026, 9, 25, 20, 0),
    )

    app._release_dashboard_payout_placeholders([row])

    assert row["Hedge Result 2.1"] == "MONDAY"


def test_payout_keeps_the_row_tradeable_when_funded_columns_are_full():
    app = _payout_app([("2026-09-23", 2100.0)])
    full = {field: "100.00" for field in TradeOpssAIApp._FUNDED_HEDGE_FIELDS}
    row = _payout_row(**full)

    assert app._release_payout_placeholders([row]) == ["Hedge Day 5"]
    assert row["Hedge Day 5"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]


def test_hand_typed_marker_waits_for_a_payout_after_the_last_dated_activity():
    app = _payout_app([("2026-09-23", 2100.0)])
    row = _payout_row(**{"_Prop Day 4 Date": "2026-09-21"})
    row.pop("_Hedge Day 5 Payout Due")

    assert app._release_payout_placeholders([row]) == [
        "Hedge Day 5", "Hedge Result 2.1"]
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]


def test_hand_typed_marker_on_a_bare_row_releases_on_any_payout():
    app = _payout_app([("2026-08-14", 1500.0)])
    row = _payout_row()
    row.pop("_Hedge Day 5 Payout Due")

    assert app._release_payout_placeholders([row]) == [
        "Hedge Day 5", "Hedge Result 2.1"]
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]
    assert app._eval_has_payout(row) is False


def test_hand_typed_marker_is_held_while_no_payout_has_landed():
    app = _payout_app([])
    row = _payout_row()
    row.pop("_Hedge Day 5 Payout Due")

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Day 5"] == "PAYOUT"