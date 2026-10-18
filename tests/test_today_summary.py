from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from trader_companion.trader_app import KENYA_TZ, TradeOpssAIApp

NOW = datetime(2026, 6, 10, 9, 0, tzinfo=KENYA_TZ)  # Wednesday morning, session open


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    monkeypatch.setattr(TradeOpssAIApp, "_today_path",
                        staticmethod(lambda: str(tmp_path / "trades_today.json")))
    app._active_trade_rows = []
    app.auto_trade_enabled = False
    app._auto_trade_scheduled_dt = None
    app._auto_trade_total = 0
    app._kyc_batch_starts = {}
    app._auto_wake_client_email = "client@example.com"
    app._auto_wake_state = {}
    app._broker_connections = {}
    app.client_email_entry = _Var("client@example.com")
    app.trading_mode_var = _Var("Simulation")
    app.direction_var = _Var("All Trades")
    return app


def _row(firm="Tradeify", acct="12345678"):
    return {"eval": {"Prop Firm": firm}, "acct_num": acct, "firm_code": firm,
            "current_phase": "Challenge"}


def test_taken_trades_are_counted_and_saved(app, tmp_path):
    app._record_trade_taken(_row("Tradeify", "A1"), "buy")
    app._record_trade_taken(_row("Lucid", "B2"), "sell", "B2-live")
    summary = app._today_summary()
    assert summary["taken"].startswith("2 taken")
    assert "Lucid 1" in summary["firms"] and "Tradeify 1" in summary["firms"]
    assert (tmp_path / "trades_today.json").exists()


def test_tally_survives_a_restart_but_not_a_new_day(app):
    app._record_trade_taken(_row(), "buy")
    day = app._today_state()["date"]
    app._today_trades = None  # simulate a fresh process
    assert len(app._today_state(datetime.fromisoformat(day + "T10:00:00+03:00"))["taken"]) == 1
    app._today_trades = None
    tomorrow = datetime.fromisoformat(day + "T10:00:00+03:00") + timedelta(days=1)
    assert app._today_state(tomorrow)["taken"] == []


def test_failures_and_skips_are_reported(app):
    app._record_trade_failed("A1", "Tradeify", "login expired")
    app._record_trade_skipped()
    app._record_trade_skipped()
    summary = app._today_summary()
    assert "1 failed" in summary["taken"] and "2 skipped" in summary["taken"]
    assert "login expired" in summary["issues"]


def test_last_trade_and_recent_list(app):
    for i in range(7):
        app._record_trade_taken(_row("Tradeify", f"ACC{i}"), "buy")
    summary = app._today_summary()
    assert "ACC6" in summary["last"] and "BUY" in summary["last"]
    assert len(summary["recent"].splitlines()) == 5


def test_idle_states(app):
    assert app._today_summary(NOW)["state"].startswith("Idle — nothing")
    app._active_trade_rows = [_row()]
    assert "1 queued" in app._today_summary(NOW)["state"]
    assert app._today_summary(NOW)["queue"] == "1 queued"


def test_armed_shows_the_shared_start_and_countdown(app):
    app.auto_trade_enabled = True
    app._auto_trade_scheduled_dt = NOW + timedelta(hours=1, minutes=12)
    app._active_trade_rows = [_row(), _row(acct="2")]
    app._auto_trade_total = 2
    summary = app._today_summary(NOW)
    assert "Armed" in summary["state"] and "1h 12m" in summary["state"]
    assert "10:12 AM EAT" in summary["start"] and "in 1h 12m" in summary["start"]
    assert summary["queue"] == "2 remaining of 2 in this batch"


def test_executing_and_started_states(app):
    app.auto_trade_enabled = True
    app._auto_trade_scheduled_dt = NOW - timedelta(minutes=5)
    app._active_trade_rows = [_row()]
    summary = app._today_summary(NOW)
    assert "Executing — 1 remaining" in summary["state"]
    assert summary["start"].endswith("(started)")


def test_complete_when_trades_were_taken_and_queue_is_empty(app):
    app._record_trade_taken(_row(), "buy")
    assert "Complete" in app._today_summary()["state"]


def test_start_falls_back_to_the_stored_kyc_batch_start(app):
    start = NOW + timedelta(minutes=30)
    app._kyc_batch_starts[app._kyc_key(NOW)] = start
    assert "9:30 AM EAT" in app._today_summary(NOW)["start"]


def test_auto_wake_states(app):
    assert "3:00" in app._today_summary(NOW)["wake"]
    app._auto_wake_state = {"scheduled_date": NOW.date().isoformat(),
                            "scheduled_at": (NOW + timedelta(hours=1)).isoformat()}
    assert "waiting" in app._today_summary(NOW)["wake"]
    assert "due now" in app._today_summary(NOW + timedelta(hours=2))["wake"]
    app._auto_wake_state["started_date"] = NOW.date().isoformat()
    assert "started today" in app._today_summary(NOW)["wake"]


def test_brokers_and_client_lines(app):
    app._broker_connections = {
        "A": {"account": SimpleNamespace(logged_in=True)},
        "B": {"account": None, "creds_source": "missing"},
    }
    app._active_trade_rows = [_row()]
    summary = app._today_summary(NOW)
    assert summary["brokers"] == "1/2 connected"
    assert "client@example.com" in summary["client"] and "1 account(s) queued" in summary["client"]
    assert summary["mode"] == "Simulation  ·  All Trades"


def test_session_line(app):
    assert app._today_summary(NOW)["session"].startswith("Open")
    saturday = datetime(2026, 6, 13, 9, 0, tzinfo=KENYA_TZ)
    assert "weekend" in app._today_summary(saturday)["session"]
    early = datetime(2026, 6, 10, 0, 30, tzinfo=KENYA_TZ)
    assert app._today_summary(early)["session"].startswith("Closed")


def test_dxtrade_fill_hook_counts_the_trade(app):
    app._mark_dxtrade_attempt = lambda code: None
    app._mark_trade_in_progress = lambda ev: []
    app._shift_day_placeholder_after_api_fill = lambda row: None
    app._record_breach_floor = lambda *a, **k: None
    app._snapshot_pre_trade_balance = lambda acct: None
    app.root = SimpleNamespace(after=lambda delay, fn=None: None)
    app._after_dxtrade_fill(_row("Tradeify247"), "dx:998877", {"balance": 50000, "sl_usd": 500}, "buy")
    entry = app._today_state()["taken"][-1]
    assert entry["account"] == "998877" and entry["side"] == "BUY"
