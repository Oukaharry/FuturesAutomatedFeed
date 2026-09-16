from unittest.mock import Mock, patch

from trader_companion.trader_app import TradeOpssAIApp


def test_tradovate_only_auto_push_runs_one_initial_full_refresh():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.auto_push_enabled = True
    app._auto_push_first_run = True
    app.log = Mock()
    app.push_data = Mock()

    with patch("trader_companion.trader_app.TRADOVATE_ONLY_MODE", True):
        app.check_and_push_update()
        app.check_and_push_update()

    app.push_data.assert_called_once_with(full_prop_refresh=True)
    assert app._auto_push_first_run is False


def test_farming_close_tracker_starts_one_poll_for_new_account():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._pending_farming_closes = {}
    app._farming_close_poll_active = False
    app.root = Mock()
    broker = Mock()

    app._track_farming_close(broker, "01419740")
    app._track_farming_close(broker, "01419740")

    assert app._pending_farming_closes["01419740"]["account"] == "01419740"
    app.root.after.assert_called_once_with(5000, app._poll_pending_farming_closes)


def test_farming_history_lines_show_account_date_and_net_pnl():
    lines = TradeOpssAIApp._format_farming_pnl_lines("Tradeify", [{
        "account_name": "TDFY-01419740",
        "mnq_daily_pnl": [{"date": "2026-09-16", "net_pnl": 175.25}],
    }])

    assert lines == [
        "🌾 Tradeify | TDFY-01419740 | 2026-09-16 | Net P/L: $+175.25"
    ]


def test_scan_resumes_unresolved_farming_zero_marker():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._broker_connections = {"Tradeify": {"account": Mock()}}
    app._track_farming_close = Mock()
    app.log = Mock()

    app._resume_pending_farming_closes([{
        "Prop Firm": "Tradeify",
        "Account #.1": "FTDFYSLX50969754357",
        "Hedge Day 1": "$0.00",
    }])

    app._track_farming_close.assert_called_once_with(
        app._broker_connections["Tradeify"]["account"], "FTDFYSLX50969754357"
    )