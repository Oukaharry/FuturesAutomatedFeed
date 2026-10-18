from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._broker_connections = {}
    app.log = Mock()
    app.root = SimpleNamespace(after=lambda _delay, fn=None, *a: fn() if fn else None)
    app._BROKER_RETRY_DELAY_SEC = 0
    return app


def test_restart_allowed_until_the_attempt_limit():
    app = _app()
    assert app._prepare_connection_restart("Firm", RuntimeError("timeout"), 1) is True
    assert app._prepare_connection_restart("Firm", RuntimeError("timeout"), 2) is True
    assert app._prepare_connection_restart("Firm", RuntimeError("timeout"), 3) is False


def test_interactive_logins_get_fewer_attempts():
    app = _app()
    limit = app._BROKER_INTERACTIVE_ATTEMPTS
    assert app._prepare_connection_restart("Vest", RuntimeError("x"), 1, limit) is True
    assert app._prepare_connection_restart("Vest", RuntimeError("x"), limit, limit) is False


@pytest.mark.parametrize("message", [
    "Invalid password", "HTTP 401", "account locked", "403 Forbidden", "Access denied"])
def test_rejected_credentials_are_never_retried(message):
    app = _app()
    assert app._prepare_connection_restart("Firm", RuntimeError(message), 1) is False
    assert "not restarting" in app.log.call_args[0][0]


def test_restart_keeps_the_broker_list_on_connecting():
    app = _app()
    app._broker_connections = {"Firm": {"account": None}}
    app._prepare_connection_restart("Firm", RuntimeError("timeout"), 1)
    assert app._broker_connections["Firm"]["reconnect_started"] > 0


def test_restart_is_cancelled_when_the_app_is_closing():
    app = _app()
    app._auto_wake_stop = SimpleNamespace(is_set=lambda: True, wait=lambda s: True)
    assert app._prepare_connection_restart("Firm", RuntimeError("timeout"), 1) is False


def test_close_failed_session_is_safe():
    closer = Mock()
    TradeOpssAIApp._close_failed_session(SimpleNamespace(close=closer))
    closer.assert_called_once()
    TradeOpssAIApp._close_failed_session(None)
    TradeOpssAIApp._close_failed_session(SimpleNamespace(close=Mock(side_effect=OSError)))


class _FakeDX:
    sessions = []
    fail_first = 1

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.host = "dx.example"
        _FakeDX.sessions.append(self)

    def login(self, api_login=True):
        if len(_FakeDX.sessions) <= _FakeDX.fail_first:
            raise RuntimeError("page did not load")

    def close(self):
        self.closed = True

    def account_codes(self):
        return ["dx:1"]


def _dx_app():
    app = _app()
    app._tradeify247_portal_fees = Mock(return_value={})
    app._sync_tradeify247_fees = Mock()
    app._mirror_broker_accounts = Mock()
    app._start_broker_idle_keepalive = Mock()
    app._start_status_poll = Mock()
    app._reconcile_connected_broker_history = Mock()
    return app


def test_dxtrade_closes_the_failed_chrome_and_starts_again(monkeypatch):
    import trader_companion.dxtrade_browser as dxb
    _FakeDX.sessions = []
    _FakeDX.fail_first = 1
    monkeypatch.setattr(dxb, "DXTradeBrowserSession", _FakeDX)
    app = _dx_app()
    app._connect_dxtrade_broker("Tradeify247", "u", "p")
    assert len(_FakeDX.sessions) == 2
    assert _FakeDX.sessions[0].closed and not _FakeDX.sessions[1].closed
    assert app._broker_connections["Tradeify247"]["account"] is _FakeDX.sessions[1]


def test_dxtrade_gives_up_after_the_attempt_limit(monkeypatch):
    import trader_companion.dxtrade_browser as dxb
    _FakeDX.sessions = []
    _FakeDX.fail_first = 99
    monkeypatch.setattr(dxb, "DXTradeBrowserSession", _FakeDX)
    app = _dx_app()
    app._connect_dxtrade_broker("Tradeify247", "u", "p")
    assert len(_FakeDX.sessions) == app._BROKER_CONNECT_ATTEMPTS
    assert all(s.closed for s in _FakeDX.sessions)
    assert "Tradeify247" not in app._broker_connections or \
        app._broker_connections["Tradeify247"].get("account") is None
    assert "connection failed" in app.log.call_args[0][0]


def test_breakout_restarts_once_then_stops(monkeypatch):
    import trader_companion.breakout_connector as bc
    created = []

    class _FakeSession:
        def __init__(self, email):
            self.closed = False
            created.append(self)

        def login(self):
            raise RuntimeError("sign-in link was not opened in time")

        def close(self):
            self.closed = True

    monkeypatch.setattr(bc, "BreakoutSession", _FakeSession)
    app = _app()
    app._connect_breakout_broker("Breakout", "me@example.com")
    assert len(created) == app._BROKER_INTERACTIVE_ATTEMPTS
    assert all(s.closed for s in created)


def test_tradovate_login_failure_closes_chrome_and_starts_again(monkeypatch):
    from trader_companion import trader_app

    created = []

    class _FakeTradovate:
        def __init__(self, user, pwd, trading_mode="Simulation"):
            self.closed = False
            self.logged_in = False
            created.append(self)

        def login(self):
            self.logged_in = len(created) > 1
            return self.logged_in

        def close(self):
            self.closed = True

    class _Var:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

        def get(self):
            return self.value or ""

    class _Entry:
        def __init__(self, text):
            self.text = text

        def get(self):
            return self.text

    class _InlineThread:
        def __init__(self, target=None, **kwargs):
            self.target = target

        def start(self):
            self.target()

    app = _app()
    conn = {"user_entry": _Entry("user"), "pass_entry": _Entry("pw"),
            "status_var": _Var(), "connect_btn": Mock(), "status_lbl": Mock()}
    app._broker_connections = {"Tradeify": conn}
    app._platform_for_firm = lambda firm: "Tradovate"
    app._is_live_connection_key = lambda firm: False
    app._firm_has_live_account = lambda firm: False
    app.trading_mode_var = _Var()
    app.broker_status_var = _Var()
    for name in ("_clear_broker_session_lost", "_start_broker_idle_keepalive",
                 "_check_all_brokers_ready", "_start_tradovate_md_feed",
                 "_start_status_poll", "_reconcile_connected_broker_history"):
        setattr(app, name, Mock())
    monkeypatch.setattr(trader_app, "TRADOVATE_AVAILABLE", True)
    monkeypatch.setattr(trader_app, "TradovateAccount", _FakeTradovate)
    monkeypatch.setattr(trader_app.threading, "Thread", _InlineThread)

    app._connect_broker_firm("Tradeify")

    assert len(created) == 2
    assert created[0].closed and not created[1].closed
    assert conn["account"] is created[1]
    assert conn["status_var"].value == "✅"

