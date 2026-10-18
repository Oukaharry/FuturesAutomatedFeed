from datetime import datetime, timedelta
from unittest.mock import Mock

from trader_companion.trader_app import KENYA_TZ, TradeOpssAIApp


def _app(email="client@example.com"):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._kyc_batch_starts = {}
    app._auto_wake_client_email = email
    app.log = Mock()
    return app


def _at(hour, minute=0):
    # Wednesday inside the trading session.
    return datetime(2026, 6, 10, hour, minute, tzinfo=KENYA_TZ)


def test_first_batch_draws_a_start_within_two_hours():
    app = _app()
    now = _at(9)
    start = app._kyc_batch_start(now)
    assert now <= start <= now + timedelta(hours=2)


def test_accounts_added_during_countdown_share_the_start_time():
    app = _app()
    first = app._kyc_batch_start(_at(9))
    later = app._kyc_batch_start(_at(9, 30))
    if first > _at(9, 30):
        assert later == first


def test_accounts_found_after_the_start_time_begin_immediately():
    app = _app()
    app._kyc_batch_starts[app._kyc_key(_at(9))] = _at(9, 15)
    late = _at(11)
    assert app._kyc_batch_start(late) == late


def test_each_client_email_gets_its_own_bunch():
    app = _app("a@example.com")
    app._kyc_batch_starts[app._kyc_key(_at(9))] = _at(10)
    app._auto_wake_client_email = "b@example.com"
    assert app._kyc_key(_at(9)) not in app._kyc_batch_starts


def test_immediate_start_is_recorded_for_later_accounts():
    app = _app()
    now = _at(7, 30)
    app._kyc_batch_starts[app._kyc_key(now)] = now
    later = _at(8, 30)
    assert app._kyc_batch_start(later) == later


def test_countdown_pending_only_before_the_shared_start():
    app = _app()
    app.auto_trade_enabled = True
    app._auto_trade_waiting_gate = True
    app._auto_trade_scheduled_dt = _at(10)
    assert app._auto_trade_countdown_pending(_at(9))
    assert not app._auto_trade_countdown_pending(_at(10, 1))
    app._auto_trade_waiting_gate = False
    assert not app._auto_trade_countdown_pending(_at(9))


def test_join_batch_adds_new_accounts_without_changing_the_start():
    app = _app()
    app._auto_trade_scheduled_dt = _at(10)
    app._active_trade_rows = [{"acct_num": "A1"}, {"acct_num": "A2"}]
    app._update_auto_trade_progress = Mock()
    app._join_kyc_batch({"A1"})
    assert app._auto_trade_total == 2
    assert app._auto_trade_scheduled_dt == _at(10)
    app._update_auto_trade_progress.assert_called_once()
    assert "joined" in app.log.call_args[0][0]
