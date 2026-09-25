"""Live companion version gate: stale running companions die on their next call."""

import dashboard.app as dapp


def _client():
    dapp.app.config['TESTING'] = True
    return dapp.app.test_client()


REQUIRED = dapp.app.config['REQUIRED_COMPANION_VERSION']


def test_companion_only_path_blocks_missing_version():
    r = _client().post('/api/client/push', json={'email': 'x@y.z'})
    assert r.status_code == 403
    assert 'TradeOpssAI client required' in r.get_json()['message']


def test_companion_only_path_blocks_stale_version():
    r = _client().post('/api/client/data', json={'email': 'x@y.z'},
                       headers={'X-Companion-Version': '1.12.4'})
    assert r.status_code == 403
    body = r.get_json()
    assert body['required_version'] == REQUIRED
    assert f'Update TradeOpssAI to v{REQUIRED}' in body['message']


def test_companion_only_path_passes_current_version():
    r = _client().post('/api/client/push', json={},
                       headers={'X-Companion-Version': REQUIRED})
    # Gate passed — endpoint then rejects the empty payload, not the version.
    assert r.status_code == 400
    assert 'Email required' in r.get_json()['message']


def test_shared_path_blocks_stale_api_key_companion():
    r = _client().post('/api/update_data', json={},
                       headers={'X-API-Key': 'any-key'})
    assert r.status_code == 403
    assert 'TradeOpssAI' in r.get_json()['message']

    r = _client().get('/api/data?client_id=Harry',
                      headers={'X-API-Key': 'any-key',
                               'X-Companion-Version': '1.11.0'})
    assert r.status_code == 403


def test_shared_path_leaves_browser_sessions_alone():
    client = _client()
    client.set_cookie('session_token', 'some-session')
    r = client.post('/api/update_data', json={})
    # Not version-gated: falls through to normal session validation.
    assert r.status_code != 403 or 'TradeOpssAI' not in (r.get_json() or {}).get('message', '')


def test_unrelated_paths_are_not_gated():
    r = _client().get('/api/client/export_csv')
    assert r.status_code != 403 or 'TradeOpssAI' not in (r.get_json() or {}).get('message', '')
