import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trader_companion import trader_app
from trader_companion.trader_app import TradeOpssAIApp


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value


class _Entry(_Var):
    pass


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._broker_connections = {}
    app.log = Mock()
    return app


def _state(conn):
    return _app()._broker_connection_state(conn)[0]


def test_disabled_account_is_reported_with_dashboard_status():
    state, label = _app()._broker_connection_state(
        {"creds_source": "disabled", "status": "banned"})
    assert state == "disabled" and "Banned" in label


def test_live_session_is_connected():
    assert _state({"account": SimpleNamespace(logged_in=True)}) == "connected"


def test_account_without_logged_in_flag_counts_as_connected():
    assert _state({"account": object()}) == "connected"


def test_logged_out_or_flagged_session_is_lost():
    assert _state({"account": SimpleNamespace(logged_in=False)}) == "lost"
    assert _state({"account": SimpleNamespace(logged_in=True),
                   "session_lost": True}) == "lost"


def test_spinner_or_recent_reconnect_means_connecting():
    assert _state({"account": None, "status_var": _Var("⏳")}) == "connecting"
    assert _state({"account": None, "reconnect_started": time.time()}) == "connecting"


def test_missing_credentials_beat_failed_status():
    conn = {"account": None, "user_entry": _Entry(""), "pass_entry": _Entry("x"),
            "status_var": _Var("❌")}
    assert _state(conn) == "missing"
    assert _state({"account": None, "creds_source": "missing"}) == "missing"


def test_failed_when_credentials_exist():
    conn = {"account": None, "user_entry": _Entry("u"), "pass_entry": _Entry("p"),
            "status_var": _Var("❌")}
    assert _state(conn) == "failed"


def test_idle_when_nothing_has_been_attempted():
    conn = {"account": None, "user_entry": _Entry("u"), "pass_entry": _Entry("p"),
            "status_var": _Var("⬚")}
    assert _state(conn) == "idle"


def test_stale_reconnect_attempt_is_no_longer_connecting():
    old = time.time() - 1000
    assert _state({"account": None, "reconnect_started": old,
                   "creds_source": "dashboard"}) == "idle"


def test_reconnect_uses_stored_action_and_closes_old_session(monkeypatch):
    app = _app()
    closed = Mock()
    reconnect = Mock()
    app._broker_connections = {
        "Vest": {"account": SimpleNamespace(logged_in=False, close=closed),
                 "reconnect": reconnect, "creds_source": "dashboard"}}
    app._redraw_broker_status_panel_if_changed = Mock()
    app._reconnect_broker("Vest")
    closed.assert_called_once()
    reconnect.assert_called_once()
    assert app._broker_connections["Vest"]["account"] is None


def test_reconnect_is_rate_limited():
    app = _app()
    reconnect = Mock()
    app._broker_connections = {
        "Vest": {"account": None, "reconnect": reconnect,
                 "reconnect_started": time.time()}}
    app._reconnect_broker("Vest")
    reconnect.assert_not_called()


def test_connected_broker_needs_confirmation(monkeypatch):
    app = _app()
    reconnect = Mock()
    app._broker_connections = {
        "Vest": {"account": SimpleNamespace(logged_in=True), "reconnect": reconnect}}
    monkeypatch.setattr(trader_app.messagebox, "askyesno", lambda *a, **k: False)
    app._reconnect_broker("Vest")
    reconnect.assert_not_called()
    assert app._broker_connections["Vest"]["account"] is not None


def test_reconnect_without_saved_login_logs_a_warning():
    app = _app()
    app._broker_connections = {"Breakout": {"account": None, "creds_source": "missing"}}
    app._reconnect_broker("Breakout")
    assert "no saved login" in app.log.call_args[0][0]


def test_reconnect_all_only_targets_unhealthy_brokers(monkeypatch):
    app = _app()
    app._broker_connections = {
        "A": {"account": SimpleNamespace(logged_in=True)},
        "B": {"account": SimpleNamespace(logged_in=False)},
        "C": {"account": None, "status_var": _Var("⏳")},
        "D": {"creds_source": "disabled", "status": "inactive"},
    }
    app._reconnect_broker = Mock()
    app.root = Mock()
    app.root.after = lambda delay, fn: fn()
    started = []

    class _Inline:
        def __init__(self, target=None, **kw):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(trader_app.threading, "Thread", _Inline)
    monkeypatch.setattr(trader_app.time, "sleep", lambda s: None)
    app._reconnect_all_brokers()
    started[0]()
    app._reconnect_broker.assert_called_once_with("B")
