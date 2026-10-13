"""DXtrade connector contract tests (no network; requests is stubbed)."""

import json

import pytest

from trader_companion.dxtrade_connector import (
    DXTradeClient, DXTradeError, new_order_code,
)


class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text if body is None else json.dumps(body)
        self.content = (self.text or "").encode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _Session:
    """Records every request; replays scripted responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params,
                           "json": json, "headers": headers or {}})
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        return self.responses.pop(0)


def _client(responses):
    sess = _Session(responses)
    c = DXTradeClient("dx.tradeify247.co", "user1", "pw", session=sess)
    return c, sess


def test_base_url_and_ws_urls_derive_from_host():
    c, _ = _client([])
    assert c.base_url == "https://dx.tradeify247.co/dxsca-web"
    assert c.ws_url == "wss://dx.tradeify247.co/dxsca-web/?format=JSON"
    assert c.ws_md_url == "wss://dx.tradeify247.co/dxsca-web/md?format=JSON"


def test_login_posts_credentials_and_stores_token():
    c, sess = _client([_Resp(200, {"sessionToken": "tok123", "timeout": "PT30M"})])

    data = c.login()

    assert data["sessionToken"] == "tok123"
    assert c.session_token == "tok123"
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/dxsca-web/login")
    assert call["json"] == {"username": "user1", "domain": "default", "password": "pw"}
    assert "Authorization" not in call["headers"]


def test_authed_requests_carry_dxapi_header():
    c, sess = _client([
        _Resp(200, {"sessionToken": "tok", "timeout": "PT30M"}),
        _Resp(200, {"metrics": [{"account": "default:1", "balance": 50000, "equity": 50010}]}),
    ])
    c.login()

    assert c.get_balance("default:1") == 50000.0
    assert sess.calls[1]["headers"]["Authorization"] == "DXAPI tok"
    assert sess.calls[1]["url"].endswith("/accounts/default%3A1/metrics")


def test_expired_token_relogins_once_and_replays():
    c, sess = _client([
        _Resp(200, {"sessionToken": "old", "timeout": "PT30M"}),
        _Resp(401, {"errorCode": "3", "description": "expired"}),
        _Resp(200, {"sessionToken": "new", "timeout": "PT30M"}),
        _Resp(200, {"positions": [{"positionCode": "p1"}]}),
    ])
    c.login()

    positions = c.list_positions("default:1")

    assert positions == [{"positionCode": "p1"}]
    assert c.session_token == "new"
    methods = [(k["method"], k["url"].rsplit("/", 1)[-1]) for k in sess.calls]
    assert methods == [("POST", "login"), ("GET", "positions"),
                       ("POST", "login"), ("GET", "positions")]


def test_bracket_is_if_then_group_with_zero_qty_close_legs():
    c, sess = _client([
        _Resp(200, {"sessionToken": "tok", "timeout": "PT30M"}),
        _Resp(200, {"orderId": 1, "updateOrderId": 1}),
    ])
    c.login()

    c.place_bracket("default:1", instrument="BTCUSDC.P", side="buy",
                    quantity=0.5, stop_price=60000, limit_price=70000,
                    order_code="abc")

    body = sess.calls[1]["json"]
    assert body["contingencyType"] == "IF-THEN"
    parent, sl, tp = body["orders"]
    assert parent == {"orderCode": "abc", "type": "MARKET", "instrument": "BTCUSDC.P",
                      "quantity": "0.5", "positionEffect": "OPEN", "side": "BUY",
                      "tif": "GTC"}
    assert sl["type"] == "STOP" and sl["stopPrice"] == "60000"
    assert tp["type"] == "LIMIT" and tp["limitPrice"] == "70000"
    for leg in (sl, tp):
        assert leg["side"] == "SELL"
        assert leg["positionEffect"] == "CLOSE"
        assert leg["quantity"] == "0"
        assert leg["tif"] == "GTC"


def test_bracket_without_protection_is_single_market_order():
    c, sess = _client([
        _Resp(200, {"sessionToken": "tok", "timeout": "PT30M"}),
        _Resp(200, {"orderId": 1, "updateOrderId": 1}),
    ])
    c.login()

    c.place_bracket("default:1", instrument="X", side="sell", quantity=1)

    body = sess.calls[1]["json"]
    assert "orders" not in body
    assert body["type"] == "MARKET" and body["side"] == "SELL"


def test_duplicate_order_code_maps_to_is_duplicate_order():
    c, _ = _client([
        _Resp(200, {"sessionToken": "tok", "timeout": "PT30M"}),
        _Resp(409, {"errorCode": "100", "description": "Order with this id already exists"}),
    ])
    c.login()

    with pytest.raises(DXTradeError) as exc:
        c.place_market("default:1", instrument="X", side="buy", quantity=1)

    assert exc.value.is_duplicate_order
    assert not exc.value.is_auth


def test_attach_protection_requires_exactly_one_price():
    c, _ = _client([])
    with pytest.raises(ValueError):
        c.attach_protection("a", position_code="1", instrument="X", close_side="sell")
    with pytest.raises(ValueError):
        c.attach_protection("a", position_code="1", instrument="X", close_side="sell",
                            stop_price=1, limit_price=2)


def test_new_order_code_is_unique():
    assert new_order_code() != new_order_code()
    assert new_order_code("z").startswith("z-")
