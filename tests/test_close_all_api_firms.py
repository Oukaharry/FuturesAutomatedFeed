"""Close All must flatten the API-only firms (MFP / Tradeify247 / Vest / Breakout)."""
from unittest.mock import Mock

from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = Mock()
    app.root.after = lambda _ms, fn, *a: fn(*a)
    return app


def test_perps_closes_each_account(monkeypatch):
    app = _app()
    client = Mock()
    client.list_accounts = lambda: {"items": [{"id": "a1", "account_number": "FP-1"},
                                               {"id": "a2", "account_number": "FP-2"}]}
    client.list_positions = lambda account_id=None: {"items": [{"id": "p"}]} if account_id == "a1" else {"items": []}
    monkeypatch.setattr("trader_companion.perps_connector.unwrap",
                        lambda r: r.get("items") if isinstance(r, dict) else r)
    flattened = []
    monkeypatch.setattr("trader_companion.perps_executor.PerpsTradeExecutor.flatten",
                        lambda self: flattened.append(self.account_id))

    closed, errors = app._close_all_api_firm("MyFundedPerps", client)

    assert (closed, errors) == (1, []) and flattened == ["a1"]


def test_vest_flattens_open_positions(monkeypatch):
    app = _app()
    client = Mock()
    client.account_id = "02b78ffa"
    client.open_positions = lambda: [{"positionId": "x", "symbol": "NDX-USD-PERP", "leverage": "5"}]
    client.close_position = lambda pid, sym, lev: {"ok": pid}

    closed, errors = app._close_all_api_firm("Vest Capital", client)

    assert (closed, errors) == (1, [])


def test_breakout_reports_per_account_and_skips_flat():
    app = _app()
    sess = Mock()
    sess.account_codes = lambda: ["AAAA-1111", "BBBB-2222"]
    sess.has_open_position_for_account = lambda code: (code == "AAAA-1111", "")
    sess.open_positions = lambda code: [{"trade_id": "t1"}]
    api = Mock()
    api.close_position = lambda tid, account_id=None: (200, {"id": tid})
    sess._ensure = lambda: api

    closed, errors = app._close_all_api_firm("Breakout Turbo", sess)

    assert (closed, errors) == (1, [])


def test_dxtrade_errors_are_surfaced():
    app = _app()
    sess = Mock()
    sess._ensure_api = lambda: True
    sess.account_codes = lambda: ["default:1S10K1"]
    sess.api.list_positions = lambda code: [{"positionCode": "pc", "symbol": "XYZ100/USD", "side": "BUY"}]

    from trader_companion.dxtrade_connector import DXTradeError
    def _boom(*a, **k):
        raise DXTradeError(400, {"description": "rejected"})
    sess.api.close_position = _boom

    closed, errors = app._close_all_api_firm("Tradeify247", sess)

    assert closed == 0 and errors and "rejected" in errors[0]
