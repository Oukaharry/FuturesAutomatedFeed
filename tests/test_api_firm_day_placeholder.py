"""API-only firms (Tradeify247 / Vest / Breakout / MyFundedPerps) advance the
weekday placeholder after a fill, like the Tradovate path does."""
from unittest.mock import Mock

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = Mock()
    app.prop_firm_mgr = Mock()
    app.prop_firm_mgr._PHASE_TRADE_ORDER = {}
    app.prop_firm_mgr.has_state_machine = lambda firm: False
    app.prop_firm_mgr.required_outcome_for_phase = lambda *a: None
    return app


def test_firm_without_trade_order_advances_positionally():
    app = _app()
    ev = {"Prop Firm": "Breakout", "Account #": "W3M6-SHMX-Y67Z-MELW",
          "Hedge Result 1": "$0.00", "Hedge Result 2": ""}

    nxt = app._resolve_next_hedge_field(ev, "Breakout", "Challenge", "Hedge Result 1")

    assert nxt == "Hedge Result 2"


def test_api_fill_marks_cell_and_queues_next_weekday(monkeypatch):
    app = _app()
    ev = {"Prop Firm": "Vest Capital", "Account #": "VEST-1", "Hedge Result 1": "WEDNESDAY"}
    row = {"eval": ev, "acct_num": "VEST-1", "firm_code": "Vest Capital",
           "current_phase": "Challenge"}
    calls = []
    app._find_day_field_name = lambda e, phase: "Hedge Result 1"
    app._mark_day_cell_traded_on_dashboard = (
        lambda acct, field, firm_code=None, current_phase=None:
        calls.append((acct, field, firm_code, current_phase)) or True)
    app._queue_day_cell_mark = Mock()

    import threading
    started = []
    real_thread = threading.Thread

    class _Inline(real_thread):
        def start(self):
            started.append(self.name)
            self.run()
    monkeypatch.setattr("trader_companion.trader_app.threading.Thread", _Inline)

    app._shift_day_placeholder_after_api_fill(row)

    assert calls == [("VEST-1", "Hedge Result 1", "Vest Capital", "Challenge")]
    app._queue_day_cell_mark.assert_not_called()


def test_api_fill_queues_retry_when_dashboard_write_fails(monkeypatch):
    app = _app()
    ev = {"Prop Firm": "Tradeify247", "Account #": "1S10K2166973", "Hedge Result 1": "WEDNESDAY"}
    row = {"eval": ev, "acct_num": "1S10K2166973", "firm_code": "Tradeify247",
           "current_phase": "Challenge"}
    app._find_day_field_name = lambda e, phase: "Hedge Result 1"
    app._mark_day_cell_traded_on_dashboard = lambda *a, **k: False
    app._queue_day_cell_mark = Mock()

    import threading

    class _Inline(threading.Thread):
        def start(self):
            self.run()
    monkeypatch.setattr("trader_companion.trader_app.threading.Thread", _Inline)

    app._shift_day_placeholder_after_api_fill(row)

    app._queue_day_cell_mark.assert_called_once_with(
        "1S10K2166973", "Hedge Result 1", "Tradeify247", "Challenge")
