"""Vest balance must include margin locked in open positions, not just free collateral."""
from trader_companion.vest_connector import VestClient, VestExecutor

ACCT = "02b78ffa-1af2-524b-85a5-85df70ea1330"


def _client(free, positions):
    c = VestClient.__new__(VestClient)
    c.account_id = ACCT
    c.accounts = lambda: [{"account_id": ACCT, "amount": str(free)}]
    c.open_positions = lambda: positions
    return c


def test_balance_adds_back_locked_collateral():
    c = _client(191.443381, [{"accountId": ACCT, "collateral": "4673.493792"}])
    assert round(c.free_collateral(), 2) == 191.44
    assert round(c.balance(), 2) == 4864.94


def test_flat_account_balance_equals_free_collateral():
    c = _client(4865.45, [])
    assert c.balance() == 4865.45


def test_other_accounts_positions_are_ignored():
    c = _client(100.0, [{"accountId": "someone-else", "collateral": "900"}])
    assert c.balance() == 100.0
