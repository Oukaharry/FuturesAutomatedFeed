"""Trade ledger: decision events at entry, outcome events at resolution."""

from unittest.mock import patch

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = lambda *a, **k: None
    return app


def test_entry_event_carries_signal_context():
    app = _app()
    app._set_signal_context('buy', source='local_ml', result={
        'confidence': 0.71, 'probability': 0.64, 'model': 'hgb_v3'})

    event = app._build_ledger_entry_event(
        account='TDFY-1', prop_firm='Tradeify', phase_key='challenge_trade1',
        platform='Tradovate', symbol='NQZ6', side='buy',
        config={'tradovate_tp_ticks': 301, 'tradovate_sl_ticks': 400})

    assert event['event'] == 'entry'
    assert event['account'] == 'TDFY-1'
    assert event['phase_key'] == 'challenge_trade1'
    assert event['tp_ticks'] == 301 and event['sl_ticks'] == 400
    assert event['signal']['direction'] == 'buy'
    assert event['signal']['confidence'] == 0.71
    assert event['signal']['model'] == 'hgb_v3'
    assert event['signal_source'] == 'local_ml'
    assert event['entry_date'] and event['entry_time']


def test_entry_event_marks_override_when_side_disagrees_with_signal():
    app = _app()
    app._set_signal_context('sell', source='broadcast')

    event = app._build_ledger_entry_event(
        account='A', prop_firm='Topstep', phase_key='funded_trade1',
        platform='Tradovate', symbol='NQZ6', side='buy')

    assert event['side'] == 'buy'
    assert event['signal']['direction'] == 'sell'
    assert event['signal_source'] == 'override(broadcast)'


def test_broadcast_context_uses_published_payload():
    app = _app()
    app._broadcast_signal_payload = {
        'confidence': 0.6, 'probability': 0.58,
        'model': 'ensemble_v2', 'published_at': '2026-09-30T10:00:00'}
    app._set_signal_context('buy', source='broadcast')

    ctx = app._last_signal_context
    assert ctx['model'] == 'ensemble_v2'
    assert ctx['published_at'] == '2026-09-30T10:00:00'


def test_ledger_queue_drains_once():
    app = _app()
    app._queue_ledger_event({'event': 'entry', 'account': 'X'})
    app._queue_ledger_event({'event': 'outcome', 'account': 'X'})

    events = app._drain_ledger_events()
    assert [e['event'] for e in events] == ['entry', 'outcome']
    assert app._drain_ledger_events() == []


def test_outcome_event_from_status_update_is_deduped():
    app = _app()
    app._primary_trade_account = lambda ev: 'TDFY-1'
    app._latest_resolved_outcome = lambda account: ('2026-09-30', 'win')
    app._trade_outcome_history = lambda force=False: {
        'tdfy-1': {'daily_pnl': [
            {'date': '2026-09-30', 'trades': 1, 'net_pnl': 1510.0}]}}

    app._queue_outcome_ledger_event({}, 'Hit TP1')
    app._queue_outcome_ledger_event({}, 'Hit TP1')  # duplicate ignored

    events = app._drain_ledger_events()
    assert len(events) == 1
    assert events[0]['outcome'] == 'tp'
    assert events[0]['net_pnl'] == 1510.0
    assert events[0]['entry_date'] == '2026-09-30'


def test_fail_status_maps_to_breach_outcome():
    app = _app()
    app._primary_trade_account = lambda ev: 'TDFY-2'
    app._latest_resolved_outcome = lambda account: ('2026-09-30', 'loss')
    app._trade_outcome_history = lambda force=False: {}

    app._queue_outcome_ledger_event({}, 'Fail')

    events = app._drain_ledger_events()
    assert events[0]['outcome'] == 'breach'


def test_server_records_ledger_events():
    from dashboard.database import record_trade_ledger_events

    calls = []
    with patch('dashboard.database.upsert_trade_ledger_entry',
               side_effect=lambda cid, e: calls.append(('entry', cid)) or True), \
         patch('dashboard.database.apply_trade_ledger_outcome',
               side_effect=lambda cid, e: calls.append(('outcome', cid)) or True):
        touched = record_trade_ledger_events('Harry', [
            {'event': 'entry', 'account': 'A', 'entry_date': '2026-09-30'},
            {'event': 'outcome', 'account': 'A', 'entry_date': '2026-09-30',
             'outcome': 'tp'},
            {'event': 'bogus'},
            'not-a-dict',
        ])
    assert touched == 2
    assert calls == [('entry', 'Harry'), ('outcome', 'Harry')]
