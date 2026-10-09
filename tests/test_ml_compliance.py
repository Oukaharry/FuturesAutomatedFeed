"""ML compliance: classification, trader attribution, payload wiring."""
from unittest.mock import patch

from dashboard.trade_attribution import (
    _signal_compliance, build_attribution_data, build_ml_compliance,
)


def test_classification():
    assert _signal_compliance({'signal_source': 'ml', 'signal_direction': 'buy',
                               'side': 'buy'}) == 'ml'
    assert _signal_compliance({'signal_source': 'ml', 'signal_direction': 'buy',
                               'side': 'sell'}) == 'against_ml'
    assert _signal_compliance({'signal_source': 'override(ml)',
                               'signal_direction': 'buy', 'side': 'buy'}) == 'against_ml'
    assert _signal_compliance({'signal_source': 'none', 'side': 'buy'}) == 'no_ml'
    assert _signal_compliance({'signal_source': 'random',
                               'signal_direction': 'buy', 'side': 'buy'}) == 'no_ml'


def test_offenders_carry_trader_and_client():
    rows = [
        {'client_id': 'Aaron', 'account': 'A1', 'prop_firm': 'Lucid',
         'side': 'sell', 'signal_direction': 'buy', 'signal_source': 'ml',
         'entry_date': '2026-10-08', 'entry_time': '2026-10-08T12:00:00',
         'outcome': 'sl', 'net_pnl': -500},
        {'client_id': 'Aaron', 'account': 'A2', 'prop_firm': 'Lucid',
         'side': 'buy', 'signal_direction': 'buy', 'signal_source': 'ml',
         'entry_date': '2026-10-08', 'entry_time': '2026-10-08T12:05:00',
         'outcome': 'tp', 'net_pnl': 700},
        {'client_id': 'Beth', 'account': 'B1', 'prop_firm': 'Topstep',
         'side': 'buy', 'signal_source': 'none',
         'entry_date': '2026-10-07', 'entry_time': '2026-10-07T09:00:00',
         'outcome': 'tp', 'net_pnl': 300},
    ]
    with patch('config.hierarchy.get_client_profile',
               side_effect=lambda c: {'Aaron': {'trader': 'Joe', 'admin': 'Harry'},
                                      'Beth': {'trader': 'Chris', 'admin': 'Harry'}}.get(c)):
        import dashboard.trade_attribution as ta
        ta._trader_cache.clear()
        mc = build_ml_compliance(rows)
    assert mc['non_ml_total'] == 2
    assert mc['summary']['ml']['n'] == 1
    kinds = {(o['trader'], o['client'], o['kind']) for o in mc['offenders']}
    assert ('Joe', 'Aaron', 'against signal') in kinds
    assert ('Chris', 'Beth', 'no signal') in kinds
    traders = {t['trader']: t for t in mc['by_trader']}
    assert traders['Joe']['against'] == 1 and traders['Joe']['clients'] == ['Aaron']


def test_payload_includes_compliance():
    data = build_attribution_data([
        {'client_id': 'X', 'side': 'buy', 'signal_source': 'none',
         'entry_date': '2026-10-08', 'outcome': 'tp', 'net_pnl': 1}])
    assert data['ml_compliance']['non_ml_total'] == 1
