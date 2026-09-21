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
        "Hedge Result 1.1": "250.00",
        "Hedge Result 2.1": "PAYOUT",
        "_Hedge Result 2.1 Payout Due": "2026-09-21",
    }
    row.update(overrides)
    return row


def test_payout_marker_blocks_trading():
    app = _scrub_app()

    assert app._eval_has_payout(_payout_row()) is True
    assert app._eval_has_payout(_payout_row(**{"Hedge Result 2.1": ""})) is False


def test_payout_marker_is_held_until_the_withdrawal_lands():
    app = _payout_app([])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Result 2.1"] == "PAYOUT"


def test_older_payouts_do_not_release_the_marker():
    app = _payout_app([("2026-08-14", 1500.0)])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Result 2.1"] == "PAYOUT"


def test_detected_payout_swaps_in_the_current_day_placeholder():
    app = _payout_app([("2026-08-14", 1500.0), ("2026-09-23", 2100.0)])
    row = _payout_row()

    assert app._release_payout_placeholders([row]) == ["Hedge Result 2.1"]
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]
    assert app._eval_has_payout(row) is False
    # The anchor is spent; a later pass must not re-release the same payout.
    assert "_Hedge Result 2.1 Payout Due" not in row


def test_hand_typed_marker_waits_for_a_payout_after_the_last_dated_activity():
    app = _payout_app([("2026-09-23", 2100.0)])
    row = _payout_row(**{"_Prop Day 5 Date": "2026-09-21"})
    row.pop("_Hedge Result 2.1 Payout Due")

    assert app._release_payout_placeholders([row]) == ["Hedge Result 2.1"]
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]


def test_hand_typed_marker_on_a_bare_row_releases_on_any_payout():
    app = _payout_app([("2026-08-14", 1500.0)])
    row = _payout_row()
    row.pop("_Hedge Result 2.1 Payout Due")

    assert app._release_payout_placeholders([row]) == ["Hedge Result 2.1"]
    assert row["Hedge Result 2.1"] in TradeOpssAIApp._WEEKDAY_LABELS[:5]
    assert app._eval_has_payout(row) is False


def test_hand_typed_marker_is_held_while_no_payout_has_landed():
    app = _payout_app([])
    row = _payout_row()
    row.pop("_Hedge Result 2.1 Payout Due")

    assert app._release_payout_placeholders([row]) == []
    assert row["Hedge Result 2.1"] == "PAYOUT"