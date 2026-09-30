"""Shared data-only MT5 fallback for clients without their own credentials."""

from unittest.mock import patch

import dashboard.app as dapp


def test_creds_present_via_hedge_account():
    data = {'hedge_accounts': [
        {'platform': 'MT5', 'login': '123', 'password': 'x', 'server': 'Srv'}]}
    assert dapp._client_mt5_creds_present(data) is True


def test_creds_present_via_legacy_mt5_credentials():
    data = {'mt5_credentials': {'login': '123', 'password': 'x', 'server': 'Srv'}}
    assert dapp._client_mt5_creds_present(data) is True


def test_creds_absent():
    assert dapp._client_mt5_creds_present({}) is False
    assert dapp._client_mt5_creds_present(
        {'hedge_accounts': [{'platform': 'MT5', 'login': '123'}],  # incomplete
         'mt5_credentials': {'login': '9'}}) is False
    assert dapp._client_mt5_creds_present(
        {'hedge_accounts': [{'platform': 'Tradovate', 'login': '1',
                             'password': 'x', 'server': 's'}]}) is False


def test_fallback_comes_from_donor_marked_data_only():
    donor_data = {'hedge_accounts': [
        {'platform': 'MT5', 'login': '555', 'password': 'pw', 'server': 'Exness'}]}
    with patch.object(dapp, 'get_client_by_email', return_value={'client': 'Harry'}), \
         patch('dashboard.database.get_client_data', return_value=donor_data):
        creds = dapp._fallback_mt5_credentials()
    assert creds == {'login': '555', 'password': 'pw', 'server': 'Exness', 'data_only': True}


def test_fallback_empty_when_donor_missing():
    with patch.object(dapp, 'get_client_by_email', return_value=None):
        assert dapp._fallback_mt5_credentials() == {}
