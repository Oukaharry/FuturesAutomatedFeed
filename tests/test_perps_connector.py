"""MyFundedPerps connector: host routing, auth, orders, errors."""

from unittest.mock import MagicMock

import pytest

from trader_companion.perps_connector import (
    LIVE_BASE, SANDBOX_BASE, MFPClient, MFPError, base_url_for_key,
)


def _client(key="fp_test_abc"):
    session = MagicMock()
    session.headers = {}
    client = MFPClient(key, session=session)
    return client, session


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.json.return_value = payload if payload is not None else {}
    return r


def test_key_prefix_routes_host():
    assert base_url_for_key("fp_test_x") == SANDBOX_BASE
    assert base_url_for_key("fp_live_x") == LIVE_BASE
    c, _ = _client("fp_test_x")
    assert c.is_sandbox
    c2, _ = _client("fp_live_x")
    assert not c2.is_sandbox


def test_bearer_header_set():
    _, session = _client("fp_test_secret")
    assert session.headers["Authorization"] == "Bearer fp_test_secret"


def test_market_id_pipe_is_encoded():
    c, session = _client()
    session.request.return_value = _resp()
    c.get_quote("binance|BTCUSDT", side="buy", size=0.001)
    url = session.request.call_args[0][1]
    assert "binance%7CBTCUSDT" in url
    assert session.request.call_args.kwargs["params"] == {"side": "buy", "size": 0.001}


def test_place_order_sends_idempotency_and_client_id():
    c, session = _client()
    session.request.return_value = _resp(payload={"id": "o1", "status": "pending"})
    out = c.place_order(account_id="a1", market_id="binance|BTCUSDT",
                        side="buy", size=0.001, expected_price=118000,
                        leverage=2, margin_mode="cross")
    assert out["id"] == "o1"
    kwargs = session.request.call_args.kwargs
    assert kwargs["headers"]["Idempotency-Key"].startswith("order-")
    body = kwargs["json"]
    assert body["client_order_id"].startswith("tradeops-")
    assert body["leverage"] == 2 and body["margin_mode"] == "cross"
    assert body["expected_price"] == 118000


def test_api_error_raises_with_payload():
    c, session = _client()
    err = _resp(status=403, payload={"error": "sandbox_access_expired",
                                     "message": "renew"})
    session.request.return_value = err
    with pytest.raises(MFPError) as e:
        c.list_accounts()
    assert e.value.status == 403
    assert e.value.payload["error"] == "sandbox_access_expired"


def test_wait_for_order_polls_until_terminal(monkeypatch):
    c, session = _client()
    states = [{"id": "o1", "status": "pending"}, {"id": "o1", "status": "filled"}]
    session.request.side_effect = [_resp(payload=s) for s in states]
    monkeypatch.setattr("time.sleep", lambda s: None)
    order = c.wait_for_order("o1", timeout_sec=5, poll_sec=0)
    assert order["status"] == "filled"


def test_close_position_auto_quotes_expected_price():
    c, session = _client()
    session.request.side_effect = [
        _resp(payload={"data": {"id": "p1", "side": "long", "size": 0.001,
                                "market_id": "binance|BTCUSDT"}}),
        _resp(payload={"data": {"mid": 82500.0}}),
        _resp(payload={"data": {"id": "o2", "status": "filled"}}),
    ]
    c.close_position("p1")
    quote_call = session.request.call_args_list[1]
    assert quote_call.kwargs["params"]["side"] == "sell"
    close_call = session.request.call_args_list[2]
    assert close_call.kwargs["json"] == {"expected_price": 82500.0}
    assert close_call.kwargs["headers"]["Idempotency-Key"].startswith("close-")
