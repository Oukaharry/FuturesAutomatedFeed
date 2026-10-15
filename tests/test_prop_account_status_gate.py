"""Prop-account Status on the dashboard decides whether the companion launches a broker."""
from unittest.mock import Mock

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = Mock()
    app.root.after = lambda _ms, fn, *a: fn(*a)
    app._broker_connections = {}
    return app


def test_status_normalisation_and_launch_gate():
    app = _app()
    assert app._prop_account_status({}) == "active"           # legacy rows without the column
    assert app._prop_account_launchable({"status": "Active"})
    assert app._prop_account_launchable({"status": " live "})
    assert not app._prop_account_launchable({"status": "Inactive"})
    assert not app._prop_account_launchable({"status": "BANNED"})


def test_api_credential_stubs_skip_inactive_and_banned_logins():
    app = _app()
    app._broker_login_family = lambda f: str(f or "").lower()
    pas = [
        {"prop_firm": "Breakout Turbo", "breakout_email": "a@x.io", "status": "Active"},
        {"prop_firm": "Vest Capital", "vest_email": "b@x.io", "status": "Banned"},
        {"prop_firm": "Tradeify247", "dxtrade_username": "u", "status": "Inactive"},
        {"prop_firm": "MyFundedPerps", "api_key": "fp_live_x", "status": "Live"},
    ]
    stubs = app._api_credential_stubs([], pas)
    assert [s["Prop Firm"] for s in stubs] == ["Breakout Turbo", "MyFundedPerps"]


def test_auto_connect_skips_disabled_and_widgetless_rows():
    app = _app()
    app._broker_login_family = lambda f: f
    app._connect_broker_firm = Mock()
    entry = lambda v: Mock(get=lambda: v)
    app._broker_connections = {
        "Tradeify": {"user_entry": entry("u"), "pass_entry": entry("p"), "account": None,
                     "creds_source": "dashboard"},
        "Apex": {"account": None, "creds_source": "disabled", "status": "banned"},   # Banned → never
        "Vest Capital": {"account": None, "row_frame": None, "creds_source": "dashboard"},  # API firm
    }

    import threading
    class _Inline(threading.Thread):
        def start(self):
            self.run()
    import trader_companion.trader_app as ta
    orig = ta.threading.Thread
    ta.threading.Thread = _Inline
    try:
        app._auto_connect_populated_brokers(priority_firms=["Tradeify"])
    finally:
        ta.threading.Thread = orig

    app._connect_broker_firm.assert_called_once_with("Tradeify")


def test_manual_connect_refuses_disabled_row():
    app = _app()
    app._broker_connections = {"Apex": {"account": None, "creds_source": "disabled", "status": "inactive"}}
    app._connect_broker_firm("Apex")
    assert "Inactive" in app.log.call_args.args[0]
