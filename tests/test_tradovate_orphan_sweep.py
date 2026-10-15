"""The flat-account orphan sweep must never strip brackets from an open trade."""
from trader_companion.tradovate import TradovateAccount


def _account(responses):
    acct = TradovateAccount.__new__(TradovateAccount)
    acct._placing_order = False
    acct.cancelled = []
    acct._api_fetch = lambda endpoint, method="GET", body=None: responses.get(endpoint)
    acct.cancel_order_api = lambda oid: acct.cancelled.append(oid)
    return acct


WORKING = [
    {"id": 1, "accountId": 7, "ordStatus": "Working"},
    {"id": 2, "accountId": 7, "ordStatus": "Working"},
]


def test_position_list_failure_is_not_treated_as_flat():
    acct = _account({"/position/list": None, "/order/list": WORKING})
    assert acct.cancel_all_orders_api(account_id=7) == 0
    assert acct.cancelled == []


def test_open_position_keeps_brackets():
    acct = _account({
        "/position/list": [{"accountId": 7, "netPos": 2}],
        "/order/list": WORKING,
    })
    assert acct.cancel_all_orders_api(account_id=7) == 0
    assert acct.cancelled == []


def test_sweep_skipped_while_order_is_being_placed():
    acct = _account({"/position/list": [], "/order/list": WORKING})
    acct._placing_order = True
    assert acct.cancel_all_orders_api(account_id=7) == 0
    assert acct.cancelled == []


def test_flat_account_orphans_are_cancelled():
    acct = _account({
        "/position/list": [{"accountId": 7, "netPos": 0}],
        "/order/list": WORKING + [{"id": 3, "accountId": 8, "ordStatus": "Working"}],
    })
    assert acct.cancel_all_orders_api(account_id=7) == 2
    assert acct.cancelled == [1, 2]
