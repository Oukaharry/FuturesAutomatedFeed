"""Attribution report: aggregation, sample guards, flags."""

from datetime import date

from dashboard.trade_attribution import build_attribution_report, _stats


def _row(outcome='tp', net=100.0, firm='Tradeify', phase='challenge_trade1',
         entry_date='2026-09-29', hour='08', source='local_ml', model='hgb_v3'):
    return {
        'outcome': outcome, 'net_pnl': net, 'prop_firm': firm,
        'phase_key': phase, 'entry_date': entry_date,
        'entry_time': f'{entry_date}T{hour}:15:00+03:00',
        'signal_source': source, 'signal_model': model,
    }


def test_stats_counts_and_pending():
    rows = [_row('tp', 100), _row('sl', -50), _row('breach', -200), _row(None)]
    n, wins, win_rate, net, pending = _stats(rows)
    assert (n, wins, pending) == (3, 1, 1)
    assert win_rate == 1 / 3
    assert net == -150


def test_report_none_without_rows():
    assert build_attribution_report([]) is None


def test_report_contains_overall_yesterday_and_breakdowns():
    rows = [_row('tp', 150) for _ in range(8)] + [_row('sl', -75) for _ in range(4)]
    text = build_attribution_report(rows, today=date(2026, 9, 30))
    assert 'Trade Attribution' in text
    assert '8W/4L (67%)' in text
    assert 'Yesterday (2026-09-29)' in text
    assert '• Tradeify: 8W/4L (67%)' in text
    assert '• Challenge: 8W/4L' in text
    assert '• 08:00 EAT:' in text
    assert '• local_ml:' in text


def test_small_groups_are_hidden():
    rows = [_row('tp'), _row('sl')]  # n=2 < MIN_BREAKDOWN_N
    text = build_attribution_report(rows, today=date(2026, 9, 30))
    assert 'By prop firm' not in text
    assert 'Trade Attribution' in text  # overall always shows


def test_flags_need_volume_and_bad_win_rate():
    losing = [_row('sl', -80, firm='Topstep') for _ in range(20)] + \
             [_row('tp', 120, firm='Topstep') for _ in range(10)]
    text = build_attribution_report(losing, today=date(2026, 9, 30))
    assert '🚩 firm `Topstep`' in text

    small = [_row('sl', -80, firm='Lucid') for _ in range(10)]
    text2 = build_attribution_report(small, today=date(2026, 9, 30))
    assert '🚩' not in text2
