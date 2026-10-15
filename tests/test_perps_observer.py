"""MyFundedPerps gets a visible terminal window like Vest / Breakout / Tradeify247."""
from unittest.mock import Mock, patch

from trader_companion import perps_login
from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = Mock()
    app.root.after = lambda _ms, fn, *a: fn(*a)
    app._broker_connections = {}
    return app


def test_observer_profile_is_per_login():
    assert perps_login.observer_profile("Harry.Odhiambo17@gmail.com") == "mfp_view_harry_odhiambo17"
    assert perps_login.observer_profile("ops@firm.io") != perps_login.observer_profile("ops2@firm.io")


def test_logged_in_requires_workspace_without_sign_in_header():
    d = Mock()
    d.execute_script = lambda js: True
    assert perps_login._logged_in(d) is True
    d.execute_script = Mock(side_effect=RuntimeError("no page"))
    assert perps_login._logged_in(d) is False


def test_connect_opens_observer_when_email_is_configured(monkeypatch):
    app = _app()
    opened = []
    app._open_perps_observer = lambda firm, email: opened.append((firm, email))
    client = Mock(is_sandbox=True)
    client.list_accounts = lambda: {"data": [{"account_number": "FP-1"}]}
    monkeypatch.setattr("trader_companion.perps_connector.MFPClient", lambda key: client)
    monkeypatch.setattr("trader_companion.perps_connector.unwrap",
                        lambda r: r.get("data") if isinstance(r, dict) else r)

    app._connect_perps_broker("MyFundedPerps", "fp_test_key", "harry@example.com")

    assert app._broker_connections["MyFundedPerps"]["account"] is client
    assert opened == [("MyFundedPerps", "harry@example.com")]


def test_observer_is_tracked_reused_and_closed_on_shutdown(monkeypatch):
    app = _app()
    driver = Mock()
    monkeypatch.setattr("trader_companion.perps_login.open_observer",
                        lambda email, otp_prompt=None: (driver, True))

    app._open_perps_observer("MyFundedPerps", "Harry@Example.com")
    assert app._perps_observers["harry@example.com"] is driver
    assert app._perps_observer_alive("harry@example.com") is True

    # Second call must not open another window.
    with patch("trader_companion.perps_login.open_observer", side_effect=AssertionError("reopened")):
        app._open_perps_observer("MyFundedPerps", "harry@example.com")

    app._close_perps_observers()
    driver.quit.assert_called_once()
    assert app._perps_observers == {}
