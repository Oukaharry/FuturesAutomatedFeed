from trader_companion.trader_app import TradeOpssAIApp, kenya_today
from trader_companion.prop_firm_manager import PropFirmManager

ACCOUNT = "TDFY-1"


class _FakeAccount:
    def __init__(self, history):
        self._history = history

    def get_trade_history(self):
        return self._history


def _app(balance):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._ai_trace = lambda *a, **k: None
    app._pending_breach_alerts = []
    app._breach_alerts_sent = set()
    app._broker_connections = {
        "Fake": {"account": _FakeAccount([{
            "account_name": ACCOUNT,
            "balance": balance,
            "daily_pnl": [{"date": kenya_today().strftime("%Y-%m-%d"),
                           "trades": 1, "net_pnl": -500.0}],
        }])}
    }
    return app


def _challenge_row():
    return {"Account #": ACCOUNT, "Prop Firm": "Tradeify"}


def _funded_row():
    return {"Account #": "TDFY-CH", "Account #.1": ACCOUNT, "Prop Firm": "Tradeify"}


def _funded_only_row():
    return {"Account #.1": ACCOUNT, "Prop Firm": "Tradeify"}


def test_challenge_breach_alerts_against_the_challenge_floor():
    app = _app(47_900.0)

    status, _reason = app._derive_account_status(_challenge_row(), "Tradeify")

    assert status == "Fail"
    assert len(app._pending_breach_alerts) == 1
    alert = app._pending_breach_alerts[0]
    assert alert["phase"] == "Challenge"
    assert alert["floor"] == 48000.0
    assert alert["balance"] == 47_900.0
    assert alert["prop_firm"] == "Tradeify"


def test_challenge_above_its_floor_does_not_alert():
    app = _app(48_500.0)

    status, _reason = app._derive_account_status(_challenge_row(), "Tradeify")

    assert status is None
    assert app._pending_breach_alerts == []


def test_funded_breach_alerts_against_the_funded_floor():
    app = _app(49_900.0)

    status, _reason = app._derive_account_status(_funded_row(), "Tradeify")

    assert status == "Fail"
    assert app._pending_breach_alerts[0]["phase"] == "Funded"
    assert app._pending_breach_alerts[0]["floor"] == 50000.0


def test_a_funded_balance_above_the_challenge_floor_still_breaches():
    # 49,900 clears the 48,000 challenge floor but is under the 50,000 funded
    # one — judging a funded account as Challenge would silently miss this.
    app = _app(49_900.0)

    assert app._derive_account_status(_challenge_row(), "Tradeify")[0] is None
    assert app._derive_account_status(_funded_row(), "Tradeify")[0] == "Fail"


def test_a_funded_only_row_is_judged_as_funded():
    # Only Account #.1 is set, so _has_passed_to_funded is False even though
    # the row is funded. It must still use the funded floor.
    app = _app(49_900.0)

    status, _reason = app._derive_account_status(_funded_only_row(), "Tradeify")

    assert status == "Fail"
    assert app._pending_breach_alerts[0]["phase"] == "Funded"
    assert app._pending_breach_alerts[0]["floor"] == 50000.0


def test_the_same_account_and_phase_only_alerts_once():
    app = _app(47_900.0)
    row = _challenge_row()

    app._derive_account_status(row, "Tradeify")
    app._derive_account_status(row, "Tradeify")

    assert len(app._pending_breach_alerts) == 1


def test_challenge_and_funded_breaches_alert_separately():
    app = _app(47_900.0)

    app._derive_account_status(_challenge_row(), "Tradeify")
    app._derive_account_status(_funded_row(), "Tradeify")

    phases = [a["phase"] for a in app._pending_breach_alerts]
    assert phases == ["Challenge", "Funded"]
