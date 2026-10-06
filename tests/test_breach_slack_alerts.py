"""Breach Slack alerts: channel routing, purchase message format, fallbacks."""

from unittest.mock import patch

import dashboard.app as dapp


def _route(admin='Kellen Njeri', user='U0ACANGNF6H', channel='C0C4K0X2APK'):
    return patch.object(dapp, '_admin_slack_route_for_client',
                        return_value=(admin, user, channel))


def test_breach_alert_posts_purchase_message_to_admin_channel():
    posts = []
    with _route(), \
         patch.object(dapp, '_slack_post', side_effect=lambda ch, txt: posts.append((ch, txt)) or True), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False):
        sent = dapp._send_admin_breach_alert('Harry', [
            {'prop_firm': 'My Funded Futures', 'account': 'A1'},
            {'prop_firm': 'MFFU Builder 50K', 'account': 'A2'},
            {'prop_firm': 'My Funded Futures', 'account': 'A3'},
        ])
    assert sent == 1
    assert posts == [('C0C4K0X2APK', '<@U0ACANGNF6H> Purchase 3 MFFU accounts for Harry')]


def test_breach_alert_groups_by_firm_and_singular_account():
    posts = []
    with _route(), \
         patch.object(dapp, '_slack_post', side_effect=lambda ch, txt: posts.append((ch, txt)) or True), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False):
        sent = dapp._send_admin_breach_alert('Harry', [
            {'prop_firm': 'Tradeify (50% Add-On)', 'account': 'T1'},
            {'prop_firm': 'Funded Next Flex', 'account': 'F1'},
            {'prop_firm': 'FundedNext', 'account': 'F2'},
        ])
    assert sent == 2
    texts = {txt for _ch, txt in posts}
    assert '<@U0ACANGNF6H> Purchase 1 Tradeify account for Harry' in texts
    assert '<@U0ACANGNF6H> Purchase 2 Funded Next accounts for Harry' in texts


def test_breach_alert_falls_back_to_dm_then_webhook():
    calls = []
    webhook = []

    def post(ch, txt):
        calls.append(ch)
        return ch.startswith('U')  # channel fails, DM works

    with _route(), \
         patch.object(dapp, '_slack_post', side_effect=post), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False):
        dapp._send_admin_breach_alert('Harry', [{'prop_firm': 'Topstep'}])
    assert calls == ['C0C4K0X2APK', 'U0ACANGNF6H']

    with _route(user='', channel=''), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False), \
         patch('dashboard.scheduler.send_slack_message', side_effect=lambda t: webhook.append(t)):
        dapp._send_admin_breach_alert('Harry', [{'prop_firm': 'Topstep'}])
    assert webhook == ['@Kellen Njeri Purchase 1 Topstep account for Harry']


def test_breach_alert_respects_pause():
    with _route(), \
         patch.object(dapp, '_slack_post', side_effect=AssertionError), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', True):
        assert dapp._send_admin_breach_alert('Harry', [{'prop_firm': 'Topstep'}]) == 0


def test_alerts_pause_state_matches_the_ops_default():
    # Deliberately paused on main until ops verifies the new pipeline in
    # production (set BREACH_SLACK_PAUSED=0 to go live without a deploy).
    assert dapp.BREACH_SLACK_NOTIFICATIONS_PAUSED is True


def test_firm_short_names():
    f = dapp._breach_firm_short_name
    assert f('My Funded Futures') == 'MFFU'
    assert f('MFFU Builder 50K') == 'MFFU'
    assert f('Tradeify (50% Add-On)') == 'Tradeify'
    assert f('Funded Next Flex') == 'Funded Next'
    assert f('Blue Guardian Reserve') == 'Blue Guardian'
    assert f('') == 'prop firm'


def test_active_trade_hold_ignores_farming_days():
    farming_only = {
        'Prop Firm': 'Tradeify',
        'Status': 'In Progress',
        'Hedge Day 3': '$0.00',      # farming fill marker
        'Hedge Day 4': 'MONDAY',     # queued farming day
    }
    assert dapp._eval_row_has_active_trade(farming_only) is False

    # Leftover $0.00 hedge cells are not positions — only live truth counts.
    challenge_marker_only = {'Prop Firm': 'Tradeify', 'Hedge Result 2': '$0.00'}
    assert dapp._eval_row_has_active_trade(challenge_marker_only) is False

    # The companion's live position flag is authoritative in both directions.
    assert dapp._eval_row_has_active_trade(
        {'Prop Firm': 'Tradeify', '_open_position': True}) is True
    assert dapp._eval_row_has_active_trade(
        {'Prop Firm': 'Tradeify', '_open_position': False,
         '_broker_balance': 50900.0, '_last_recorded_balance': 50000.0}) is False

    # Fallback for older companions: a real balance gap means an open trade.
    assert dapp._eval_row_has_active_trade(
        {'Prop Firm': 'Tradeify',
         '_broker_balance': 50900.0, '_last_recorded_balance': 50000.0}) is True

    # A queued weekday placeholder is a plan, not a position.
    funded_queued = {'Prop Firm': 'Tradeify', 'Hedge Result 1.1': 'TUESDAY'}
    assert dapp._eval_row_has_active_trade(funded_queued) is False


def test_firm_with_only_farming_activity_does_not_hold_batches():
    evaluations = [{
        'Prop Firm': 'Tradeify',
        'Status P1': 'Pass',
        'Status': 'In Progress',
        'Hedge Day 5': '$0.00',
    }]
    assert dapp._firm_has_active_trades(evaluations, dapp._breach_firm_family('Tradeify')) is False


def test_clear_pending_endpoint_requires_super_admin():
    client = dapp.app.test_client()
    assert client.post('/api/breach_alerts/clear_pending').status_code == 401


def test_clear_pending_endpoint_clears_queues():
    handler = getattr(dapp.api_clear_pending_breach_alerts, '__wrapped__',
                      dapp.api_clear_pending_breach_alerts)
    with patch('dashboard.database.clear_all_breach_alert_pending', return_value=3) as clear:
        with dapp.app.test_request_context():
            resp = handler()
        assert resp.get_json() == {'status': 'success', 'cleared_queues': 3}
        clear.assert_called_once()


def _flush_env(monkeypatch, pending, recent_firms, saved):
    monkeypatch.setattr('dashboard.database.get_breach_alert_pending',
                        lambda c: list(pending))
    monkeypatch.setattr('dashboard.database.set_breach_alert_pending',
                        lambda c, p: saved.update({'pending': p}))
    monkeypatch.setattr('dashboard.database.get_breach_alert_sent_batches',
                        lambda c: set())
    monkeypatch.setattr('dashboard.database.mark_breach_alert_batch_sent',
                        lambda c, k: None)
    monkeypatch.setattr('dashboard.database.get_client_recent_ledger_firms',
                        lambda c, days=7: set(recent_firms))


def test_holds_survive_session_end_and_wrong_firms_drop(monkeypatch):
    pending = [
        {'account': 'A1', 'prop_firm': 'Tradeify', 'phase': 'Challenge'},  # row missing → hold
        {'account': 'B1', 'prop_firm': 'FTMO', 'phase': 'Challenge'},      # firm not run → drop
    ]
    saved = {}
    _flush_env(monkeypatch, pending, {'Tradeify'}, saved)
    evaluations = [{'Prop Firm': 'Tradeify', 'Account #': 'T9',
                    'Status P1': 'In Progress'}]
    with _route(), patch.object(dapp, '_kenya_now') as now, \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False), \
         patch.object(dapp, '_send_admin_breach_alert', return_value=1):
        now.return_value.hour = 21              # after session end
        now.return_value.weekday.return_value = 1
        dapp._flush_batched_breach_alerts('Harry', evaluations)
    accounts = [b['account'] for b in saved['pending']]
    assert 'A1' in accounts      # a hold is never destroyed
    assert 'B1' not in accounts  # client doesn't run FTMO


def test_at_cap_purchase_requeues_instead_of_vanishing(monkeypatch):
    pending = [{'account': 'M4', 'prop_firm': 'MFFU', 'phase': 'Challenge'}]
    saved = {}
    _flush_env(monkeypatch, pending, {'MFFU'}, saved)
    evaluations = [
        {'Prop Firm': 'MFFU', 'Account #': f'M{i}', 'Status P1': 'In Progress'}
        for i in (1, 2, 3)
    ] + [{'Prop Firm': 'MFFU', 'Account #': 'M4', 'Status P1': 'Fail'}]
    sent = []
    with _route(), patch.object(dapp, '_kenya_now') as now, \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False), \
         patch.object(dapp, '_send_admin_breach_alert',
                      side_effect=lambda c, b: sent.append(b) or len(b)):
        now.return_value.hour = 21
        now.return_value.weekday.return_value = 1
        dapp._flush_batched_breach_alerts('Harry', evaluations)
    assert sent == []  # cap full (3 live rows) — nothing announced
    assert [b['account'] for b in saved['pending']] == ['M4']  # kept for later


def test_vanished_row_breach_sends_after_session(monkeypatch):
    pending = [{'account': 'GONE1', 'prop_firm': 'Tradeify', 'phase': 'Challenge',
                'reason_code': 'tradovate_vanish'}]
    saved = {}
    _flush_env(monkeypatch, pending, {'Tradeify'}, saved)
    sent = []
    with _route(), patch.object(dapp, '_kenya_now') as now, \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False), \
         patch.object(dapp, '_send_admin_breach_alert',
                      side_effect=lambda c, b: sent.append(b) or len(b)):
        now.return_value.hour = 21
        now.return_value.weekday.return_value = 1
        dapp._flush_batched_breach_alerts('Harry', [])
    assert len(sent) == 1 and sent[0][0]['account'] == 'GONE1'
    assert saved['pending'] == []


def test_placeholder_rows_do_not_occupy_max_out_slots():
    rows = [
        {'Prop Firm': 'MFFU', 'Account #': 'M1', 'Status P1': 'In Progress'},
        {'Prop Firm': 'MFFU', 'Status P1': 'Not Started'},  # no account yet
    ]
    assert dapp._eval_row_occupies_max_out_slot(rows[0]) is True
    assert dapp._eval_row_occupies_max_out_slot(rows[1]) is False
