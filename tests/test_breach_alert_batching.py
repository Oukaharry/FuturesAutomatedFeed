"""Challenge breach alerts batch per firm until all its challenge accounts close."""

from unittest.mock import Mock, patch

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app._pending_breach_alerts = []
    app._breach_alerts_sent = set()
    app._held_challenge_breaches = {}
    app._broker_login_family = lambda firm: str(firm or '').strip().lower().split(' (')[0]
    app._account_has_open_position = lambda ev: False
    app._resolve_trade_outcome = lambda account: 'loss'
    return app


def _record(app, account, firm, phase):
    app._record_breach_alert(
        {'Prop Firm': firm, 'Account #': account}, firm, phase, 47900.0, 48000.0)


def test_challenge_breaches_are_held_and_funded_send_immediately():
    app = _app()
    app._primary_trade_account = lambda ev: ev.get('Account #')

    _record(app, 'T1', 'Tradeify', 'Challenge')
    _record(app, 'T2', 'Tradeify', 'Challenge')
    _record(app, 'F1', 'Tradeify', 'Funded')

    assert [b['account'] for b in app._pending_breach_alerts] == ['F1']
    assert len(app._held_challenge_breaches['tradeify']) == 2


def test_held_breaches_release_when_no_challenge_account_is_pending():
    app = _app()
    app._primary_trade_account = lambda ev: ev.get('Account #')
    _record(app, 'T1', 'Tradeify', 'Challenge')
    _record(app, 'T2', 'Tradeify', 'Challenge')

    # Remaining rows for the firm are terminal — nothing pending.
    evaluations = [
        {'Prop Firm': 'Tradeify', 'Account #': 'T1', 'Status P1': 'Fail'},
        {'Prop Firm': 'Tradeify', 'Account #': 'T2', 'Status P1': 'Fail'},
        {'Prop Firm': 'Tradeify', 'Account #': 'T3', 'Status P1': 'Pass'},
    ]
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 12
        app._release_held_breach_alerts(evaluations)

    assert sorted(b['account'] for b in app._pending_breach_alerts) == ['T1', 'T2']
    assert app._held_challenge_breaches == {}


def test_held_breaches_wait_for_open_position_and_unresolved_trades():
    app = _app()
    app._primary_trade_account = lambda ev: ev.get('Account #')
    _record(app, 'T1', 'Tradeify', 'Challenge')

    open_pos = [
        {'Prop Firm': 'Tradeify', 'Account #': 'T1', 'Status P1': 'Fail'},
        {'Prop Firm': 'Tradeify', 'Account #': 'T3', 'Status P1': 'In Progress',
         'Hedge Result 1': '$0.00'},
    ]
    app._account_has_open_position = lambda ev: ev.get('Account #') == 'T3'
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 12
        app._release_held_breach_alerts(open_pos)
    assert app._pending_breach_alerts == []

    # Position closed but outcome not settled yet — still waiting.
    app._account_has_open_position = lambda ev: False
    app._resolve_trade_outcome = lambda account: None
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 12
        app._release_held_breach_alerts(open_pos)
    assert app._pending_breach_alerts == []

    # Outcome resolved — release.
    app._resolve_trade_outcome = lambda account: 'win'
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 12
        app._release_held_breach_alerts(open_pos)
    assert [b['account'] for b in app._pending_breach_alerts] == ['T1']


def test_session_end_flushes_held_breaches_regardless():
    app = _app()
    app._primary_trade_account = lambda ev: ev.get('Account #')
    _record(app, 'T1', 'Tradeify', 'Challenge')

    still_open = [
        {'Prop Firm': 'Tradeify', 'Account #': 'T3', 'Status P1': 'In Progress',
         'Hedge Result 1': '$0.00'},
    ]
    app._account_has_open_position = lambda ev: True
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 20
        app._release_held_breach_alerts(still_open)

    assert [b['account'] for b in app._pending_breach_alerts] == ['T1']


def test_other_firms_do_not_block_release():
    app = _app()
    app._primary_trade_account = lambda ev: ev.get('Account #')
    _record(app, 'T1', 'Tradeify', 'Challenge')

    evaluations = [
        {'Prop Firm': 'Tradeify', 'Account #': 'T1', 'Status P1': 'Fail'},
        {'Prop Firm': 'Topstep', 'Account #': 'S1', 'Status P1': 'In Progress',
         'Hedge Result 1': '$0.00'},
    ]
    app._account_has_open_position = lambda ev: ev.get('Account #') == 'S1'
    with patch('trader_companion.trader_app.kenya_now') as now:
        now.return_value.hour = 12
        app._release_held_breach_alerts(evaluations)

    assert [b['account'] for b in app._pending_breach_alerts] == ['T1']
