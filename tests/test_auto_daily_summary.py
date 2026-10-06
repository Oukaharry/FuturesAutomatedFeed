"""Automated daily summary: manual format, sections filled from evidence."""

from datetime import datetime, timezone

from dashboard.auto_daily_summary import (
    build_checklist_items, build_client_summary_text, firm_display,
)

_NOW = datetime(2026, 10, 6, 20, 5, tzinfo=timezone.utc)  # Tuesday


def _evals():
    return [
        {'Prop Firm': 'Tradeify', 'Account #': 'T1', 'Status P1': 'In Progress'},
        {'Prop Firm': 'My Funded Futures', 'Account #': 'M1', 'Status': 'In Progress',
         'Hedge Result 1.1': 'PAYOUT'},
        {'Prop Firm': 'Old Firm', '_deleted': True},
    ]


def _ledger():
    return [
        {'prop_firm': 'Tradeify', 'outcome': 'tp'},
        {'prop_firm': 'Tradeify', 'outcome': 'tp'},
        {'prop_firm': 'My Funded Futures', 'outcome': 'sl'},
    ]


def _events():
    return [
        {'kind': 'purchase_sent', 'prop_firm': 'Tradeify', 'detail': '2'},
        {'kind': 'status_change', 'prop_firm': 'Tradeify', 'detail': 'Fail'},
        {'kind': 'breach_queued', 'prop_firm': 'Tradeify', 'detail': 'Challenge'},
    ]


def _payout(ev):
    return any(str(v).strip().upper() == 'PAYOUT' for v in ev.values()
               if isinstance(v, str))


def test_summary_matches_manual_format_and_tags_admin():
    text = build_client_summary_text(
        'Harry', trader='Tangara', admin='Philip Tangara',
        admin_slack_id='U123', evaluations=_evals(), ledger_rows=_ledger(),
        events=_events(), has_payout_pending=_payout, now=_NOW)
    assert '👤 Trader: Tangara' in text
    assert '🏢 Admin: <@U123>' in text
    assert '📋 **DAILY SUMMARY — Harry**' in text
    assert '📅 Tuesday, October 06, 2026' in text
    # Section 1: purchases announced today
    assert '⚠️ Tradeify: 2 challenge(s) pending purchase' in text
    # Section 4: payout eligible per firm (display name mapping)
    assert '⚠️ MFFU: 1 payout(s) eligible at Next Trading Day' in text
    # Section 7: trade counts from the ledger
    assert '✅ Tradeify: 2 trades hit TP today' in text
    assert '✅ MFFU: 1 trade hit SL today' in text
    # Status flips surface under action items
    assert 'status updated today: 1 fail' in text
    assert text.rstrip().endswith("🤖 Auto-generated from the day's recorded activity")


def test_quiet_day_is_all_ok():
    text = build_client_summary_text(
        'Harry', trader='T', admin='A', evaluations=_evals(),
        ledger_rows=[], events=[], has_payout_pending=lambda ev: False, now=_NOW)
    assert '✅ All challenges purchased and funded' in text
    assert '✅ No payout requests pending.' in text
    assert '✅ No trades taken today.' in text
    assert '⚠️' not in text
    assert '🏢 Admin: @A' in text  # falls back to name without a Slack id


def test_checklist_items_mirror_the_sections():
    items = build_checklist_items(events=_events(), ledger_rows=_ledger(),
                                  payouts={'MFFU': 1})
    by_id = {i['id']: i for i in items}
    assert by_id['challenge_purchase']['status'] == 'warn'
    assert by_id['challenge_purchase']['notes']['Tradeify']['fields']['count'] == '2'
    assert by_id['payout_requests']['notes']['MFFU']['fields']['count'] == '1'
    assert by_id['trade_count']['status'] == 'warn'
    assert by_id['renewal_cancel']['status'] == 'ok'
    assert by_id['slack_sent']['status'] == 'ok'  # tracker counts the send
    assert [i['num'] for i in items if 'num' in i] == [1, 2, 3, 4, 5, 6, 7]


def test_firm_display_names():
    assert firm_display('My Funded Futures') == 'MFFU'
    assert firm_display('Topstep') == 'TopStep'
    assert firm_display('Funded Next Flex') == 'Funded Next'
    assert firm_display('Lucid') == 'Lucid'
