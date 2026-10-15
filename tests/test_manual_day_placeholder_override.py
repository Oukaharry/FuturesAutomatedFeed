from unittest.mock import Mock

import pytest

from dashboard.app import merge_dashboard_update_evaluations
from trader_companion.trader_app import TradeOpssAIApp


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("Hit TP1", "win"), ("Hit SL1", "loss")],
)
def test_reconcile_queues_next_day_when_fill_cell_is_already_marked(status, outcome):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app._latest_resolved_outcome = lambda _account: ("2026-10-15", outcome)
    app._get_phase_fields = lambda _phase: ["Hedge Result 1", "Hedge Result 2"]
    app._resolve_firm_code = lambda _firm: "Tradeify"
    app._resolve_next_hedge_field = lambda *args, **kwargs: "Hedge Result 2"
    app._next_trading_weekday = lambda: 4
    row = {
        "Account #": "ACCT-1",
        "Prop Firm": "Tradeify",
        "Status P1": status,
        "Hedge Result 1": "$0.00",
        "Hedge Result 2": "",
    }

    changed = app._reconcile_traded_day_placeholders([row])

    assert row["Hedge Result 2"] == "FRIDAY"
    assert "Hedge Result 2" in changed


def test_dashboard_manual_day_placeholder_survives_terminal_row_cleanup():
    existing = [{
        "Prop Firm": "Tradeify",
        "Account #": "ACCT-1",
        "Status P1": "Fail",
        "Hedge Result 1": "",
    }]
    incoming = [{
        **existing[0],
        "Hedge Result 1": "FRIDAY",
    }]

    merged = merge_dashboard_update_evaluations(
        existing,
        incoming,
        {0: {"Hedge Result 1"}},
        {"Hedge Result 1"},
        {"Hedge Result 1"},
    )

    assert merged[0]["Hedge Result 1"] == "FRIDAY"
    assert "Hedge Result 1" in merged[0]["_manual_push_fields"]


def test_companion_terminal_cleanup_preserves_manually_entered_day():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    row = {
        "Account #": "ACCT-1",
        "Status P1": "Fail",
        "Hedge Result 1": "FRIDAY",
        "_manual_push_fields": ["Hedge Result 1"],
    }

    app._scrub_failed_row_day_placeholders([row])

    assert row["Hedge Result 1"] == "FRIDAY"


def test_reconcile_does_not_repopulate_a_manually_cleared_next_day():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app._latest_resolved_outcome = lambda _account: ("2026-10-15", "win")
    app._get_phase_fields = lambda _phase: ["Hedge Result 1", "Hedge Result 2"]
    app._resolve_firm_code = lambda _firm: "Tradeify"
    app._resolve_next_hedge_field = lambda *args, **kwargs: "Hedge Result 2"
    app._next_trading_weekday = lambda: 4
    row = {
        "Account #": "ACCT-1",
        "Prop Firm": "Tradeify",
        "Status P1": "Hit TP1",
        "Hedge Result 1": "$0.00",
        "Hedge Result 2": "",
        "_cleared_fields": ["Hedge Result 2"],
    }

    changed = app._reconcile_traded_day_placeholders([row])

    assert row["Hedge Result 2"] == ""
    assert changed == []
