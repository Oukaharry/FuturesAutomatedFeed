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


def test_alerts_are_live_by_default():
    # BREACH_SLACK_PAUSED defaults to '0'; ops sets it to 1 to pause.
    assert dapp.BREACH_SLACK_NOTIFICATIONS_PAUSED is False


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

    challenge_active = {'Prop Firm': 'Tradeify', 'Hedge Result 2': '$0.00'}
    assert dapp._eval_row_has_active_trade(challenge_active) is True

    funded_active = {'Prop Firm': 'Tradeify', 'Hedge Result 1.1': 'TUESDAY'}
    assert dapp._eval_row_has_active_trade(funded_active) is True


def test_firm_with_only_farming_activity_does_not_hold_batches():
    evaluations = [{
        'Prop Firm': 'Tradeify',
        'Status P1': 'Pass',
        'Status': 'In Progress',
        'Hedge Day 5': '$0.00',
    }]
    assert dapp._firm_has_active_trades(evaluations, dapp._breach_firm_family('Tradeify')) is False
