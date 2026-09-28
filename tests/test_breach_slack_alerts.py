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
    assert posts == [('C0C4K0X2APK', '<@U0ACANGNF6H> Purchase 3 MFFU accounts')]


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
    assert '<@U0ACANGNF6H> Purchase 1 Tradeify account' in texts
    assert '<@U0ACANGNF6H> Purchase 2 Funded Next accounts' in texts


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
    assert webhook == ['@Kellen Njeri Purchase 1 Topstep account']


def test_breach_alert_respects_pause():
    with _route(), \
         patch.object(dapp, '_slack_post', side_effect=AssertionError), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', True):
        assert dapp._send_admin_breach_alert('Harry', [{'prop_firm': 'Topstep'}]) == 0


def test_alerts_are_unpaused_by_default():
    assert dapp.BREACH_SLACK_NOTIFICATIONS_PAUSED is False


def test_firm_short_names():
    f = dapp._breach_firm_short_name
    assert f('My Funded Futures') == 'MFFU'
    assert f('MFFU Builder 50K') == 'MFFU'
    assert f('Tradeify (50% Add-On)') == 'Tradeify'
    assert f('Funded Next Flex') == 'Funded Next'
    assert f('Blue Guardian Reserve') == 'Blue Guardian'
    assert f('') == 'prop firm'
