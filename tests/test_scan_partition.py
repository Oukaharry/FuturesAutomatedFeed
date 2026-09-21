from trader_companion.trader_app import TradeOpssAIApp
from trader_companion.prop_firm_manager import PropFirmManager


MONDAY = 0


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *args, **kwargs: None
    app._sync_prop_firm_from_account = lambda ev: None
    return app


def _row(**overrides):
    row = {
        "Prop Firm": "Tradeify",
        "Account #": "TDFY-1",
        "Status P1": "In Progress",
        "_is_active": True,
    }
    row.update(overrides)
    return row


def test_row_with_todays_placeholder_both_trades_and_connects():
    app = _app()
    row = _row(**{"Hedge Result 1": "MONDAY"})

    active, connect, _ = app._partition_evaluations_for_scan([row], MONDAY)

    assert active == [row]
    assert connect == [row]


def test_active_account_without_todays_placeholder_still_connects():
    app = _app()
    row = _row(**{"Hedge Result 1": "THURSDAY"})

    active, connect, skipped = app._partition_evaluations_for_scan([row], MONDAY)

    assert active == []
    assert connect == [row]
    assert skipped["no_day"] == 1


def test_account_with_no_placeholders_at_all_still_connects():
    app = _app()
    row = _row()

    active, connect, _ = app._partition_evaluations_for_scan([row], MONDAY)

    assert active == []
    assert connect == [row]


def test_payout_blocked_funded_row_still_connects():
    app = _app()
    row = _row(**{
        "Account #.1": "TDFY-2",
        "Status P1": "Pass",
        "Status": "In Progress",
        "Hedge Result 2.1": "PAYOUT",
    })

    active, connect, _ = app._partition_evaluations_for_scan([row], MONDAY)

    assert active == []
    assert connect == [row]


def test_inactive_rows_neither_trade_nor_connect():
    app = _app()
    deleted = _row(**{"_deleted": True})
    failed = _row(**{"_is_active": False, "Status P1": "Fail"})
    no_account = _row(**{"Account #": "", "Hedge Result 1": "MONDAY"})

    active, connect, skipped = app._partition_evaluations_for_scan(
        [deleted, failed, no_account], MONDAY)

    assert active == []
    assert connect == []
    assert skipped["inactive"] == 3
