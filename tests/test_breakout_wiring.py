"""Breakout companion wiring + executor tests (no Chrome, no network)."""

import time

import pytest

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp
from trader_companion import breakout_connector as bc
from trader_companion.breakout_connector import BreakoutExecutor, BreakoutSession

ACCT = "W3M6-SHMX-Y67Z-MELW"
USD = lambda a: {"amount": f"{a:.4f}", "asset": {"name": "USD", "class": "currency"}}
REC = {"id": ACCT, "name": "Turbo Eval 1", "type": "prop_paper", "status": "active",
       "plan": {"initial_size": USD(5000), "target_equity_value": USD(5450),
                "max_drawdown_equity_value": USD(4850), "max_daily_loss_equity_value": USD(4850)},
       "portfolio": {"balance": USD(5000), "equity": USD(5000), "upnl": USD(0), "daily_pnl": USD(0),
                     "used_margin": USD(0), "available_margin": USD(5000), "balance_at_rollover": USD(5000),
                     "daily_pnl_window_resets_at": "2026-10-15T00:30:00Z"}}
XYZ = {"name": "XYZ100/USD", "min_lot": "0.0001", "lot_decimals": 8, "tick_size": "1", "price_decimals": 5,
       "status": "EXTERNAL_PAIR_STATUS_ENABLED", "max_leverage": "10",
       "effective_settings": {"buy_leverage": "10", "sell_leverage": "10"}}


class _FakeAPI:
    def __init__(self):
        self.account_id = ACCT
        self.orders = []
        self.protects = []
        self.closes = []
        self.margin = 0.0
        self.trades_rows = []

    def accounts(self): return [REC]
    def account(self, aid=None): return REC
    def overview(self, aid=None): return {"summary": {"used_margin": USD(self.margin)}}
    def markets(self, symbols=None): return {"result": {"data": [{"symbol": "XYZ100/USD", "price": "30000.00"}]}}
    def get(self, path):
        if path.startswith("/prop-trading/v1/markets/external"):
            return 200, {}, {"pairs": [XYZ]}
        if path.startswith("/positions"):
            return 200, {}, {"result": []}
        if path.startswith("/trades/history"):
            return 200, {}, {"result": {"trades": self.trades_rows}}
        if path.startswith("/session/expiration"):
            return 200, {"x-internal-auth": "x"}, {}
        return 404, {}, {}
    def place_market(self, pair, side, volume, take_profit=None, stop_loss=None, reduce_only=False, account_id=None):
        self.orders.append({"pair": pair, "side": side, "volume": volume, "tp": take_profit, "sl": stop_loss})
        self.margin = 30.0
        self.trades_rows = [{"transaction_id": "XTOPEN", "pair": pair, "position_status": "open",
                             "time": str(time.time()), "misc": ["initiated"]}]
        return 200, {"result": {"order_id": "XO1"}, "errors": []}
    def protect(self, tid, take_profit=None, stop_loss=None, account_id=None):
        self.protects.append(tid)
        return 400, {"errors": [{"type": "protection_order_already_exists"}]}
    def close_position(self, tid, amount=None, account_id=None):
        self.closes.append(tid); self.margin = 0.0; self.trades_rows = []
        return 200, {"result": {"order_id": "XOC"}}
    def close(self): pass


def _session():
    s = BreakoutSession("x@example.com")
    s.api = _FakeAPI()
    return s


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._broker_connections = {}
    app._on_funded_leg = lambda ev: False
    app._funded_payout_count = lambda ev: 0
    return app


# ── identity / routing ─────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["Breakout", "breakout prop", "BreakoutProp", "Breakout Classic"])
def test_is_breakout_firm(label):
    assert _app()._is_breakout_firm(label)


@pytest.mark.parametrize("label", ["Vest Capital", "Tradeify247", "MyFundedPerps", "Tradeify", ""])
def test_is_breakout_firm_rejects_others(label):
    assert not _app()._is_breakout_firm(label)


def test_breakout_routing():
    app = _app()
    class _V:
        def get(self): return "Tradovate"
    app.broker_var = _V()
    assert app._is_api_only_firm("Breakout")
    assert app._platform_for_firm("Breakout") == "Breakout"
    assert app._broker_login_family("Breakout Prop") == "Breakout"
    assert TradeOpssAIApp._FIRM_MAP["Breakout Prop"] == "Breakout"


# ── session facade ────────────────────────────────────────────────────

def test_facade_contract():
    s = _session()
    assert s.account_codes() == [ACCT]
    assert s._code_for(ACCT) == ACCT and s._code_for("W3M6 SHMX Y67Z MELW") == ACCT and s._code_for("MELW") == ACCT
    assert s.has_open_position_for_account(ACCT) == (False, "flat")
    h = s.get_trade_history()[0]
    assert h["account_name"] == ACCT and h["balance"] == 5000 and h["balance_sod"] == 5000
    me = s.get_min_equity(ACCT)
    assert me["min_equity"] == 4850 and me["target_equity"] == 5450 and me["daily_reset_at"].startswith("2026-10-15")


# ── executor ──────────────────────────────────────────────────────────

def test_plan_sizes_to_leverage_and_tick():
    ex = BreakoutExecutor(_session(), ACCT)
    plan = ex.plan_bracket("XYZ100/USD", "buy", tp_usd=470, sl_usd=125)
    # 5000 × 0.97 × 10x / 30000 = 1.6166…, floored to 0.0001
    assert plan["quantity"] == pytest.approx(1.6166, abs=1e-4)
    assert plan["leverage"] == 10 and plan["tick"] == 1
    assert plan["tp_price"] > 30000 > plan["sl_price"]
    assert plan["tp_price"] == int(plan["tp_price"]) and plan["sl_price"] == int(plan["sl_price"])
    assert plan["tp_pts"] == pytest.approx(470 / plan["quantity"], rel=1e-3)
    assert plan["sl_pts"] == pytest.approx(125 * 0.95 / plan["quantity"], rel=1e-3)


def test_plan_sell_fixed_qty_and_min_lot():
    ex = BreakoutExecutor(_session(), ACCT)
    plan = ex.plan_bracket("XYZ100/USD", "sell", tp_usd=1, sl_usd=1, quantity=0.001)
    assert plan["quantity_str"] == "0.001" and plan["tp_price"] < 30000 < plan["sl_price"]
    with pytest.raises(ValueError):
        ex.plan_bracket("XYZ100/USD", "buy", tp_usd=1, sl_usd=1, quantity=0.00001)


def test_execute_places_market_with_inline_protection_and_confirms():
    s = _session()
    ex = BreakoutExecutor(s, ACCT)
    plan = ex.plan_bracket("XYZ100/USD", "buy", tp_usd=10, sl_usd=10, quantity=0.001)
    res = ex.execute(plan)
    o = s.api.orders[0]
    assert o["side"] == "buy" and o["volume"] == "0.001" and o["tp"] == plan["tp_price_str"] and o["sl"] == plan["sl_price_str"]
    assert res["position_id"] == "XTOPEN" and res["protected"] is True
    assert s.has_open_position_for_account(ACCT)[0] is True
    assert ex.flatten()[0]["trade_id"] == "XTOPEN" and s.has_open_position_for_account(ACCT) == (False, "flat")


def test_symbol_for_now(monkeypatch):
    monkeypatch.delenv("BREAKOUT_SYMBOL", raising=False)
    assert bc.symbol_for_now(1) == "XYZ100/USD" and bc.symbol_for_now(6) == "BTC/USD"


# ── companion plan hook ───────────────────────────────────────────────

def test_breakout_plan_for_row_uses_classic_rules_scaled_to_live_account():
    app = _app()
    s = _session()
    row = {"acct_num": ACCT, "eval": {"Prop Firm": "Breakout"}, "firm_code": "Breakout"}
    executor, code, plan = app._breakout_plan_for_row(s, row, "buy")
    bp = plan["blueprint"]
    assert code == ACCT and bp["attempt"] == 1
    # Turbo $5K = 0.1 × Classic: budget $145, cost $20 → price stop $125, price target $450+$20
    assert bp["risk_budget"] == 145 and bp["sl_usd"] == 125 and bp["tp_usd"] == 470
    # Temporary live-test cap: Turbo rules pin the bracket to ±$100 (SL × 0.95 buffer)
    assert plan["sl_usd"] == pytest.approx(100 * 0.95) and plan["tp_usd"] == 100


def test_breakout_plan_blocks_same_window_repeat():
    app = _app()
    s = _session()
    app._mark_breakout_attempt(ACCT)
    row = {"acct_num": ACCT, "eval": {"Prop Firm": "Breakout"}, "firm_code": "Breakout"}
    with pytest.raises(RuntimeError, match="00:30 UTC"):
        app._breakout_plan_for_row(s, row, "buy")


# ── saved login → live accounts → dashboard rows ──────────────────────

def test_credential_stub_added_when_no_row_exists():
    app = _app()
    app._broker_firm_aliases = {}
    pas = [{"prop_firm": "Breakout Turbo", "breakout_email": "h@example.com"},
           {"prop_firm": "Breakout", "breakout_email": ""},
           {"prop_firm": "Topstep", "tradovate_username": "u", "tradovate_password": "p"}]
    stubs = app._api_credential_stubs([], pas)
    assert stubs == [{"Prop Firm": "Breakout Turbo", "_credential_stub": True}]
    # an existing Breakout-family row means no stub is needed
    assert app._api_credential_stubs([{"Prop Firm": "Breakout", "Account #": ACCT}], pas) == []


def test_breakout_mirror_rows_build_tradeable_turbo_row():
    app = _app()
    app._last_dashboard_evaluations = []
    rows = app._breakout_mirror_rows("Breakout Turbo", _session())
    assert len(rows) == 1
    r = rows[0]
    assert r["Prop Firm"] == "Breakout Turbo" and r["Account #"] == ACCT
    assert r["Account Size"] == "$5,000" and r["Status P1"] == "In Progress"
    assert r["Hedge Result 1"] == app._api_row_day_placeholder()
    from trader_companion.trader_app import kenya_today
    active, connect, skipped = app._partition_evaluations_for_scan(rows, kenya_today().weekday())
    assert len(active) == 1 and skipped["no_day"] == 0


def test_mirror_skips_accounts_already_on_dashboard():
    app = _app()
    app._last_dashboard_evaluations = [{"Prop Firm": "Breakout", "Account #": ACCT.replace("-", " ")}]
    rows = app._breakout_mirror_rows("Breakout Turbo", _session())
    known = app._dashboard_account_keys()
    assert app._account_match_key(rows[0]["Account #"]) in known
