"""Tradeify247 / DXtrade companion wiring tests (no network, no Chrome)."""

import pytest

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp
from trader_companion.dxtrade_executor import DXTradeExecutor


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._broker_connections = {}
    return app


# ── identity ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["Tradeify247", "tradeify 247", "TRADEIFY247 (DXtrade)", "dxtrade"])
def test_is_dxtrade_firm_matches_variants(label):
    assert _app()._is_dxtrade_firm(label)


@pytest.mark.parametrize("label", ["Tradeify", "Tradeify Select", "Tradeify (50% Add-On)", "MyFundedPerps", ""])
def test_is_dxtrade_firm_rejects_tradovate_tradeify_and_others(label):
    assert not _app()._is_dxtrade_firm(label)


def test_api_only_covers_both_perps_and_dxtrade():
    app = _app()
    assert app._is_api_only_firm("MyFundedPerps")
    assert app._is_api_only_firm("Tradeify247")
    assert not app._is_api_only_firm("Tradeify")


def test_tradeify247_has_its_own_login_family_not_tradeify():
    app = _app()
    assert app._broker_login_family("Tradeify247") == "Tradeify247"
    assert app._broker_login_family("Tradeify Select") == "Tradeify"
    assert app._broker_login_family("Tradeify247") != app._broker_login_family("Tradeify")


def test_platform_for_tradeify247_is_dxtrade():
    app = _app()
    class _V:  # broker_var stub
        def get(self): return "Tradovate"
    app.broker_var = _V()
    assert app._platform_for_firm("Tradeify247") == "DXtrade"
    assert app._platform_for_firm("Tradeify") != "DXtrade"


def test_firm_map_resolves_tradeify247():
    assert TradeOpssAIApp._FIRM_MAP["Tradeify247"] == "Tradeify247"
    assert TradeOpssAIApp._FIRM_MAP["Tradeify 247"] == "Tradeify247"


@pytest.mark.parametrize("acct", ["1S10K2166973", "default:1S10K2166973", "2S50K1", "IF25K99"])
def test_prop_firm_manager_detects_tradeify247_accounts(acct):
    m = PropFirmManager()
    assert m.detect_prop_firm(acct) == "Tradeify247"
    assert m.detect_firm_from_account(acct) == "Tradeify247"


@pytest.mark.parametrize("acct,expected", [
    ("TDFYSL50469269857", "Tradeify"), ("FTDFYSLX50828842633", "Tradeify"),
    ("MFFUEVFLX545395115", "MFFU"),
])
def test_tradeify247_detection_does_not_steal_other_firms(acct, expected):
    assert PropFirmManager().detect_prop_firm(acct) == expected


# ── executor sizing ────────────────────────────────────────────────────

class _FakeClient:
    """Minimal DXTradeClient stand-in for plan_bracket math."""

    def __init__(self, balance=10000.0, available=10000.0, margin_rate=0.5,
                 min_size=0.01, step=0.01):
        self._m = {"balance": balance, "equity": balance, "availableBalance": available}
        self._det = {"minOrderSize": min_size, "minOrderSizeIncrement": step,
                     "marginRate": {"tiers": [{"value": margin_rate}]},
                     "tradingStatus": "FULL"}

    def _acct(self, code): return code
    def _get(self, path, **kw): return {"instrumentDetails": [self._det]}
    def get_metrics(self, account): return dict(self._m)


def test_plan_sizes_to_available_margin_and_converts_dollars_to_points():
    ex = DXTradeExecutor(_FakeClient(balance=10000, available=10000, margin_rate=0.5), "default:X")
    plan = ex.plan_bracket("XYZ100/USD", "buy", ref_price=30000.0, tp_usd=100.0, sl_usd=50.0)
    # notional cap = 10000*0.97 / 0.5 = 19400 → 0.64 lots at 30000
    assert plan["quantity"] == pytest.approx(0.64)
    assert plan["margin"] == pytest.approx(0.64 * 30000 * 0.5)
    assert plan["leverage"] == 2.0
    # $-per-point == quantity; SL gets the 0.95 risk buffer
    assert plan["tp_pts"] == pytest.approx(100.0 / 0.64, rel=1e-3)
    assert plan["sl_pts"] == pytest.approx(50.0 * 0.95 / 0.64, rel=1e-3)
    assert plan["tp_price"] > plan["ref_price"] > plan["sl_price"]


def test_plan_sell_flips_tp_sl_sides():
    ex = DXTradeExecutor(_FakeClient(), "a")
    plan = ex.plan_bracket("XYZ100/USD", "sell", ref_price=30000.0, tp_usd=10, sl_usd=10, quantity=0.01)
    assert plan["tp_price"] < plan["ref_price"] < plan["sl_price"]


def test_plan_respects_fixed_quantity_and_min_size():
    ex = DXTradeExecutor(_FakeClient(), "a")
    plan = ex.plan_bracket("XYZ100/USD", "buy", ref_price=30000.0, tp_usd=10, sl_usd=10, quantity=0.05)
    assert plan["quantity"] == 0.05
    with pytest.raises(ValueError):
        ex.plan_bracket("XYZ100/USD", "buy", ref_price=30000.0, tp_usd=10, sl_usd=10, quantity=0.001)


def test_plan_refuses_when_trading_status_not_full():
    c = _FakeClient()
    c._det["tradingStatus"] = "CLOSE_ONLY"
    with pytest.raises(ValueError):
        DXTradeExecutor(c, "a").plan_bracket("XYZ100/USD", "buy", ref_price=30000.0,
                                             tp_usd=10, sl_usd=10)


# ── Tradeify247 portal billing → Fee ───────────────────────────────────

def test_portal_fees_by_login_maps_paid_orders():
    from trader_companion.tradeify247_portal import Tradeify247Portal
    p = Tradeify247Portal("x@example.com", "pw")
    p.orders = lambda status="": [
        {"orderId": 48697, "status": "Paid", "createdAt": "2026-10-14T10:00:00Z", "total": "60.00",
         "currency_symbol": "$", "propAccount": {"traderAccountLogin": "1S10K2167015", "password": "secret"}},
        {"orderId": 48600, "status": "Cancelled", "createdAt": "2026-10-13T10:00:00Z", "total": "431",
         "propAccount": {"traderAccountLogin": "1S50K0000001"}},
    ]
    fees = p.fees_by_login()
    assert fees["1S10K2167015"] == 60.0 and "1S50K0000001" not in fees


def test_dxtrade_mirror_row_uses_portal_fee_and_tier_size():
    from trader_companion.prop_firm_manager import PropFirmManager
    from trader_companion.trader_app import TradeOpssAIApp
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    class _Sess:
        def account_codes(self): return ["default:1S10K2167015"]
    rows = app._dxtrade_mirror_rows("Tradeify247", _Sess(), fees={"1S10K2167015": 60.0})
    assert rows[0]["Account Size"] == "$10,000" and rows[0]["Fee"] == "60"
    rows = app._dxtrade_mirror_rows("Tradeify247", _Sess(), fees={})
    assert rows[0]["Fee"] == "0"
