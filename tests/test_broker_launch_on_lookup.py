"""Brokers open right after client lookup; Tradovate only for the client's live firms."""
from unittest.mock import Mock, patch

from trader_companion.trader_app import TradeOpssAIApp


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = Mock()
    app.root.after = lambda _ms, fn, *a: fn(*a)  # run scheduled callbacks inline
    app.client_email_entry = Mock(get=lambda: "harry@example.com")
    app.url_entry = Mock(get=lambda: "https://dash.example.com")
    app._populate_broker_rows = Mock()
    app._resume_pending_account_closes = Mock()
    app._api_credential_stubs = lambda ce, pa: []
    app._broker_login_family = lambda f: str(f or "").strip().lower().split(" (")[0]
    app._is_superseded_lifecycle_row = lambda ev, evs: False
    app._sync_prop_firm_from_account = lambda ev: None
    app._eval_has_payout = lambda ev: False
    app._on_funded_leg = lambda ev: False
    app._has_passed_to_funded = lambda ev: False
    app._has_placeholder_for_weekday = lambda ev, wd: ev.get("_today", False)
    return app


def test_launch_connects_only_live_firms_without_a_scan(monkeypatch):
    app = _app()
    payload = {
        "evaluations": [
            {"Prop Firm": "Tradeify", "Account #": "T1", "_is_active": True, "_today": True},
            {"Prop Firm": "Lucid", "Account #": "L1", "_is_active": True},        # live, no trade today
            {"Prop Firm": "Apex", "Account #": "A1", "_is_active": False},        # failed → no Chrome
            {"Prop Firm": "TopStep", "Account #": "", "_is_active": True},       # no account → skip
        ],
        "prop_accounts": [{"prop_firm": "Apex", "tradovate_username": "x", "tradovate_password": "y"}],
    }

    class _Thread:
        def __init__(self, target=None, daemon=None, name=None, **_):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr("trader_companion.trader_app.threading.Thread", _Thread)
    with patch("trader_companion.trader_app.requests.post", return_value=_Resp(payload)):
        app._launch_brokers_now()

    app._populate_broker_rows.assert_called_once()
    connect_evals, prop_accounts = app._populate_broker_rows.call_args.args
    assert [ev["Prop Firm"] for ev in connect_evals] == ["Tradeify", "Lucid"]
    assert app._populate_broker_rows.call_args.kwargs["priority_firms"] == ["Tradeify"]
    assert app._broker_launch_in_flight is False


def test_lookup_success_schedules_the_broker_launch():
    src = open("trader_companion/trader_app.py", encoding="utf-8").read()
    i = src.index("self.root.after(400, self._auto_connect_mt5)")
    assert "self._launch_brokers_now" in src[i:i + 400]
